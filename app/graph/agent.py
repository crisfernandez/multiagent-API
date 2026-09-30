from typing import Literal
from pydantic import BaseModel, Field
from langchain_ollama import ChatOllama
from langgraph.graph import StateGraph, MessagesState, START, END
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, BaseMessage
from app.graph.state import PlanMusical, SpotifyState
from app.graph.tools import sp

from .tools import buscar_canciones, analizar_metricas_audio, crear_playlist_en_cuenta


llm = ChatOllama(model="qwen2.5:3b", temperature=0)
planner_llm = llm.with_structured_output(PlanMusical)

def nodo_planner(state: SpotifyState):
    """Único nodo que usa el LLM: extrae los parámetros de la petición del usuario."""
    prompt = SystemMessage(content=(
        "Analiza la petición musical del usuario y genera los parámetros para la búsqueda. "
        "Define el mejor término de búsqueda, un nombre atractivo para la playlist y el criterio de ordenación."
    ))
    plan: PlanMusical = planner_llm.invoke([prompt] + state["messages"])
    
    return {
        "termino_busqueda": plan.termino_busqueda,
        "nombre_playlist": plan.nombre_playlist,
        "criterio_orden": plan.criterio_orden,
        "messages": [AIMessage(content=f"Planificado: buscar '{plan.termino_busqueda}' para la playlist '{plan.nombre_playlist}'.")]
    }


def nodo_scout(state: SpotifyState):
    """Python puro (0.1s): busca las canciones en Spotify evitando sobrecarga."""
    query = state.get("termino_busqueda", "rock")
    res = sp.search(q=query, type="track", limit=5)
    
    canciones = []
    for item in res.get("tracks", {}).get("items", []):
        canciones.append({
            "id": item.get("id"),
            "nombre": item.get("name"),
            "artista": item.get("artists", [{}])[0].get("name"),
            "popularidad": item.get("popularity"),
            "duracion_ms": item.get("duration_ms")
        })
    
    return {"canciones_seleccionadas": canciones}


def nodo_dj(state: SpotifyState):
    """Python puro (0.001s): ordena las canciones sin gastar inferencias ni sufrir error 403."""
    canciones = state.get("canciones_seleccionadas", [])
    criterio = state.get("criterio_orden", "popularidad")
    
    # Ordenación determinista instantánea
    if criterio == "duracion":
        canciones_ordenadas = sorted(canciones, key=lambda x: x["duracion_ms"])
    else:
        canciones_ordenadas = sorted(canciones, key=lambda x: x["popularidad"], reverse=True)
    
    track_ids = [c["id"] for c in canciones_ordenadas]
    
    resumen = "\n".join([f"- {c['nombre']} ({c['artista']})" for c in canciones_ordenadas])
    mensaje_dj = (
        f"He preparado la selección para '{state['nombre_playlist']}':\n{resumen}\n\n"
        "Todo está listo para guardarse en tu Spotify."
    )
    
    return {
        "canciones_seleccionadas": canciones_ordenadas,
        "track_ids": track_ids,
        "messages": [AIMessage(content=mensaje_dj)]
    }


def nodo_gestor(state: SpotifyState):
    """Python puro (0.2s): crea la playlist real. Este es el nodo protegido por HITL."""
    nombre = state.get("nombre_playlist", "Mi Playlist de IA")
    track_ids = state.get("track_ids", [])
    
    user_id = sp.me()["id"]
    playlist = sp.user_playlist_create(user=user_id, name=nombre, public=True)
    
    uris = [f"spotify:track:{t_id}" for t_id in track_ids]
    if uris:
        sp.playlist_add_items(playlist_id=playlist["id"], items=uris)
        
    return {
        "messages": [AIMessage(content=f"¡Éxito! Playlist '{nombre}' creada con {len(track_ids)} canciones.")]
    }


# --- 4. CONSTRUCCIÓN DEL GRAFO ---
workflow = StateGraph(SpotifyState)

workflow.add_node("planner", nodo_planner)
workflow.add_node("scout", nodo_scout)
workflow.add_node("dj", nodo_dj)
workflow.add_node("gestor", nodo_gestor)

# Flujo secuencial instantáneo
# 1. Inicio hacia el planificador (único paso LLM)
workflow.add_edge(START, "planner")

# 2. Paso directo: Planner -> Scout (búsqueda en Spotify)
workflow.add_edge("planner", "scout")

# 3. Paso directo: Scout -> DJ (ordenación por Python)
workflow.add_edge("scout", "dj")

# 4. Paso hacia el Gestor (aquí actúa interrupt_before=["gestor"])
workflow.add_edge("dj", "gestor")

# 5. Fin del flujo tras crear la playlist
workflow.add_edge("gestor", END)

checkpointer = MemorySaver()

# Freno HITL: Se detiene exactamente antes de tocar la cuenta del usuario en 'gestor'
graph = workflow.compile(
    checkpointer=checkpointer,
    interrupt_before=["gestor"]
)