import uuid

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_ollama import ChatOllama
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from app.graph.state import AnalisisEmocional, ClasificacionIntencion, EstadoRecomendador
from app.graph.tools import SIN_RESULTADOS, buscar_peliculas

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
    return {
        "tipo_intencion": clasificacion.tipo,
        "termino_busqueda": entidad,
        "keywords": [],
        "messages": [HumanMessage(content=mensaje)],
    }


# 2. NODO ANALIZADOR DEL ESTADO DE ÁNIMO DEL USUARIO
def nodo_analizar_mood(state: EstadoRecomendador) -> dict:
    mensaje = state["mensaje_usuario"]
    prompt = f"""
    Eres un psicólogo experto en cine. Analiza el siguiente texto y deduce el estado
    de ánimo o energía del usuario. Devuelve un resumen corto y entre 3 y 5 palabras
    clave temáticas (conceptos, valores, subgéneros) para buscar en el catálogo.

    Mensaje: {mensaje}
    """
    analisis: AnalisisEmocional = llm_psicologo.invoke(prompt)
    keywords = [k.strip() for k in (analisis.keywords or []) if k and k.strip()][:5]
    return {
        "mood_detectado": analisis.mood_detectado,
        "keywords": keywords,
    }


# NODO 3: Prepara la llamada a la tool (no ejecuta SQL aquí, lo hace el ToolNode)
def nodo_preparar_busqueda(state: EstadoRecomendador) -> dict:
    tipo = state.get("tipo_intencion")
    termino = (state.get("termino_busqueda") or "").strip() or None
    keywords = state.get("keywords") or []

    args: dict = {}
    if tipo == "actor" and termino:
        args = {"actor": termino}
    elif tipo == "genero" and termino:
        args = {"genero": termino}
    elif tipo == "mood" and keywords:
        args = {"keywords": keywords}
    else:
        # Sin criterios válidos: llamada vacía para que la tool devuelva SIN_RESULTADOS
        args = {}

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


# NODO 4: Redactor (Genera la respuesta final en Markdown)
def nodo_redactar(state: EstadoRecomendador) -> dict:
    peliculas = SIN_RESULTADOS
    for msg in reversed(state.get("messages", [])):
        if isinstance(msg, ToolMessage):
            peliculas = msg.content
            break
    if not peliculas:
        peliculas = state.get("peliculas_encontradas") or SIN_RESULTADOS

    tipo = state.get("tipo_intencion")
    mood = state.get("mood_detectado")

    contexto = f"El usuario se siente: {mood}." if mood else f"El usuario buscó por: {tipo}."
    sin_resultados = peliculas == SIN_RESULTADOS

    prompt = f"""
    Eres un recomendador de cine amable y servicial.
    {contexto}

    Aquí tienes las películas encontradas en nuestro catálogo:
    {peliculas}

    Redacta una respuesta cercana presentándole las películas de forma atractiva.
    Conserva siempre el título, la puntuación y las URLs de los carteles si están disponibles.
    {"IMPORTANTE: no hay resultados. Dilo con honestidad y sugiere 2-3 búsquedas alternativas. No inventes películas." if sin_resultados else ""}
    """
    respuesta = llm.invoke(prompt)
    return {"peliculas_encontradas": peliculas, "respuesta_final": respuesta.content}


def bifurcar_segun_intencion(state: EstadoRecomendador) -> str:
    tipo = state.get("tipo_intencion")
    # Si es mood, pasa primero por el psicólogo. Si no, prepara la búsqueda.
    if tipo == "mood":
        return "analizar_mood"
    if tipo in ("actor", "genero"):
        return "preparar_busqueda"
    return "pedir_aclaracion"


# ========================================================
# CONSTRUCCIÓN DEL GRAFO
# ========================================================
tool_node = ToolNode([buscar_peliculas])

workflow = StateGraph(EstadoRecomendador)

workflow.add_node("router", nodo_router)
workflow.add_node("analizar_mood", nodo_analizar_mood)
workflow.add_node("preparar_busqueda", nodo_preparar_busqueda)
workflow.add_node("tools", tool_node)
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

# La búsqueda pasa por el ToolNode real y luego al redactor
workflow.add_edge("preparar_busqueda", "tools")
workflow.add_edge("tools", "redactar")

workflow.add_edge("redactar", END)
workflow.add_edge("pedir_aclaracion", END)

memory = MemorySaver()
grafo = workflow.compile(checkpointer=memory)
# Alias para compatibilidad con imports antiguos
graph = grafo
