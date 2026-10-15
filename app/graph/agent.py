import json
import uuid
from typing import List

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_ollama import ChatOllama
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from app.graph.state import AnalisisEmocional, ClasificacionIntencion, EstadoRecomendador
from app.graph.tools import SIN_RESULTADOS, buscar_peliculas, detectar_termino_catalogo

LIMITE_POOL = 60  # candidatos que deja la tool para paginar/refrescar sin repetir el LLM

llm = ChatOllama(model="qwen2.5:3b", temperature=0)
llm_router = llm.with_structured_output(ClasificacionIntencion)
llm_psicologo = llm.with_structured_output(AnalisisEmocional)


# 1. NODO ENRUTADOR: Clasifica y extrae entidades
def nodo_router(state: EstadoRecomendador) -> dict:
    mensaje = state["mensaje_usuario"]
    prompt = f"""
    Analiza este mensaje y determina si el usuario busca por un actor en particular,
    por un género cinematográfico concreto, o si expresa un estado de ánimo/tema libre (mood).
    Si es actor o género, extrae el nombre en el campo entidad.

    Mensaje: {mensaje}
    """
    clasificacion: ClasificacionIntencion = llm_router.invoke(prompt)
    entidad = (clasificacion.entidad or "").strip() or None
    # Reset de la búsqueda anterior: con MemorySaver el estado del hilo persiste
    # entre invocaciones, así que hay que limpiarlo si no, arrastraríamos
    # respaldo_mood/ya_reintentado/peliculas de la búsqueda previa.
    return {
        "tipo_intencion": clasificacion.tipo,
        "termino_busqueda": entidad,
        "keywords": [],
        "generos_mood": [],
        "mood_detectado": None,
        "ya_reintentado": False,
        "respaldo_mood": False,
        "peliculas": [],
        "respuesta_final": None,
        "messages": [HumanMessage(content=mensaje)],
    }


# 2. NODO ANALIZADOR DEL ESTADO DE ÁNIMO DEL USUARIO
def nodo_analizar_mood(state: EstadoRecomendador) -> dict:
    mensaje = state["mensaje_usuario"]
    prompt = f"""
    Eres un psicólogo experto en cine. Analiza el siguiente texto y deduce el estado
    de ánimo o energía del usuario.
    - Devuelve 1 a 3 géneros de la lista permitida que mejor encajen con ese ánimo.
    - Devuelve 2 o 3 palabras clave EN INGLÉS pensadas para buscar en un catálogo de
      cine (tipo TMDB): conceptos descriptivos como friendship, vacation, feel good,
      revenge, survival. NO las traduzcas al español.

    Mensaje: {mensaje}
    """
    analisis: AnalisisEmocional = llm_psicologo.invoke(prompt)
    generos = [g.strip() for g in (analisis.generos or []) if g and g.strip()][:3]
    keywords = [k.strip() for k in (analisis.keywords or []) if k and k.strip()][:5]
    return {
        "mood_detectado": analisis.mood_detectado,
        "generos_mood": generos,
        "keywords": keywords,
    }


# NODO 3: Prepara la llamada a la tool (no ejecuta SQL aquí, lo hace el ToolNode)
def nodo_preparar_busqueda(state: EstadoRecomendador) -> dict:
    tipo = state.get("tipo_intencion")
    termino = (state.get("termino_busqueda") or "").strip() or None
    keywords = state.get("keywords") or []

    args: dict = {"limite": LIMITE_POOL}
    if tipo == "actor" and termino:
        args["actor"] = termino
    elif tipo == "genero" and termino:
        args["genero"] = termino
    elif tipo == "mood":
        # Mood: géneros en español (criterio principal) + keywords TMDB en inglés.
        generos = state.get("generos_mood") or []
        if generos:
            args["generos"] = generos
        if keywords:
            args["keywords"] = keywords
    # Sin criterios válidos: la tool devolverá el catálogo ordenado por nota.

    return {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": buscar_peliculas.name,
                        "args": args,
                        "id": f"buscar-{uuid.uuid4().hex[:8]}",
                    }
                ],
            )
        ]
    }


def nodo_pedir_aclaracion(state: EstadoRecomendador) -> dict:
    respuesta = (
        "No he entendido si buscas por actor, género o estado de ánimo. "
        "Dime por ejemplo: 'películas de Tom Hanks', 'quiero comedia' o 'necesito desconectar'."
    )
    return {"respuesta_final": respuesta}


# NODO 5: Extrae el resultado estructurado que dejó el ToolNode en el estado
def nodo_extraer_resultados(state: EstadoRecomendador) -> dict:
    contenido = None
    for msg in reversed(state.get("messages", [])):
        if isinstance(msg, ToolMessage):
            contenido = msg.content
            break

    peliculas: List[dict] = []
    if isinstance(contenido, str) and contenido:
        try:
            datos = json.loads(contenido)
            peliculas = datos.get("peliculas") or []
        except (json.JSONDecodeError, TypeError, AttributeError):
            peliculas = []
    elif isinstance(contenido, dict):
        peliculas = contenido.get("peliculas") or []

    return {"peliculas": peliculas}


# NODO 6: Reintenta la búsqueda usando la heurística sobre el catálogo
# (cuando el router del LLM no acertó, p. ej. "películas con Tom Hanks").
def nodo_reintentar_catalogo(state: EstadoRecomendador) -> dict:
    heuristica = detectar_termino_catalogo(state.get("mensaje_usuario") or "")
    args: dict = {"limite": LIMITE_POOL}
    tipo = state.get("tipo_intencion")
    termino = state.get("termino_busqueda")

    if heuristica:
        tipo = heuristica["tipo"]
        termino = heuristica["termino"]
        if tipo == "actor":
            args["actor"] = termino
        elif tipo == "genero":
            args["genero"] = termino
        elif tipo == "titulo":
            args["titulo"] = termino

    return {
        "ya_reintentado": True,
        "tipo_intencion": tipo,
        "termino_busqueda": termino,
        "messages": [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": buscar_peliculas.name,
                        "args": args,
                        "id": f"reintentar-{uuid.uuid4().hex[:8]}",
                    }
                ],
            )
        ],
    }


# NODO 7: Respaldo del mood — vuelve a pedir a la tool sin filtros
# (lo mejor valorado) para no dejar la pantalla vacía.
def nodo_respaldo_mood(state: EstadoRecomendador) -> dict:
    return {
        "ya_reintentado": True,
        "respaldo_mood": True,
        "messages": [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": buscar_peliculas.name,
                        "args": {"limite": LIMITE_POOL},
                        "id": f"respaldo-{uuid.uuid4().hex[:8]}",
                    }
                ],
            )
        ],
    }


# NODO 4: Redactor (Genera la respuesta final en Markdown)
def nodo_redactar(state: EstadoRecomendador) -> dict:
    peliculas = state.get("peliculas") or []
    tipo = state.get("tipo_intencion")
    mood = state.get("mood_detectado")

    contexto = f"El usuario se siente: {mood}." if mood else f"El usuario buscó por: {tipo}."
    sin_resultados = not peliculas
    catalogo = json.dumps(peliculas, ensure_ascii=False, indent=1) if peliculas else SIN_RESULTADOS

    prompt = f"""
    Eres un recomendador de cine amable y servicial.
    {contexto}

    Aquí tienes las películas encontradas en nuestro catálogo:
    {catalogo}

    Redacta una respuesta cercana presentándole las películas de forma atractiva.
    Conserva siempre el título, la puntuación y las URLs de los carteles si están disponibles.
    {"IMPORTANTE: no hay resultados. Dilo con honestidad y sugiere 2-3 búsquedas alternativas. No inventes películas." if sin_resultados else ""}
    """
    respuesta = llm.invoke(prompt)
    return {"respuesta_final": respuesta.content}


def bifurcar_segun_intencion(state: EstadoRecomendador) -> str:
    tipo = state.get("tipo_intencion")
    # Si es mood, pasa primero por el psicólogo. Si no, prepara la búsqueda.
    if tipo == "mood":
        return "analizar_mood"
    if tipo in ("actor", "genero"):
        # Un título concreto puede venir clasificado como actor/género: la tool
        # y el reintento se encargan de encontrarlo por título.
        return "preparar_busqueda"
    return "pedir_aclaracion"


def bifurcar_tras_busqueda(state: EstadoRecomendador) -> str:
    """Decide si el agente buscador debe reintentar o si ya podemos redactar."""
    if state.get("peliculas"):
        return "redactar"
    if state.get("ya_reintentado"):
        return "redactar"
    if state.get("tipo_intencion") == "mood":
        return "respaldo_mood"
    if detectar_termino_catalogo(state.get("mensaje_usuario") or ""):
        return "reintentar_catalogo"
    return "redactar"


# ========================================================
# CONSTRUCCIÓN DEL GRAFO
# ========================================================
tool_node = ToolNode([buscar_peliculas])

workflow = StateGraph(EstadoRecomendador)

workflow.add_node("router", nodo_router)
workflow.add_node("analizar_mood", nodo_analizar_mood)
workflow.add_node("preparar_busqueda", nodo_preparar_busqueda)
workflow.add_node("tools", tool_node)
workflow.add_node("extraer_resultados", nodo_extraer_resultados)
workflow.add_node("reintentar_catalogo", nodo_reintentar_catalogo)
workflow.add_node("respaldo_mood", nodo_respaldo_mood)
workflow.add_node("redactar", nodo_redactar)
workflow.add_node("pedir_aclaracion", nodo_pedir_aclaracion)

workflow.add_edge(START, "router")

workflow.add_conditional_edges(
    "router",
    bifurcar_segun_intencion,
    {
        "analizar_mood": "analizar_mood",
        "preparar_busqueda": "preparar_busqueda",
        "pedir_aclaracion": "pedir_aclaracion",
    },
)

# El nodo de mood siempre continúa hacia la preparación de la búsqueda
workflow.add_edge("analizar_mood", "preparar_busqueda")

# La búsqueda pasa por el ToolNode y luego el resultado se extrae al estado
workflow.add_edge("preparar_busqueda", "tools")
workflow.add_edge("tools", "extraer_resultados")

# Si salió vacío, el agente buscador puede reintentar (heurística o respaldo)
workflow.add_conditional_edges(
    "extraer_resultados",
    bifurcar_tras_busqueda,
    {
        "redactar": "redactar",
        "reintentar_catalogo": "reintentar_catalogo",
        "respaldo_mood": "respaldo_mood",
    },
)
workflow.add_edge("reintentar_catalogo", "tools")
workflow.add_edge("respaldo_mood", "tools")

workflow.add_edge("redactar", END)
workflow.add_edge("pedir_aclaracion", END)

memory = MemorySaver()
grafo = workflow.compile(checkpointer=memory)
