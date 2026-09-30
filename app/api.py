from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from langchain_core.messages import HumanMessage, ToolMessage
from app.graph.agent import graph

app = FastAPI(title="Enterprise Agent API")

class ChatRequest(BaseModel):
    thread_id: str
    mensaje: str

class ResumeRequest(BaseModel):
    thread_id: str
    aprobado: bool

@app.post("/chat")
def chat_endpoint(payload: ChatRequest):
    config = {"configurable": {"thread_id": payload.thread_id}}
    graph.invoke({"messages": [HumanMessage(content=payload.mensaje)]}, config=config)
    
    estado = graph.get_state(config)
    if "tools" in estado.next:
        llamada = estado.values["messages"][-1].tool_calls[0]
        return {
            "status": "REQUIRES_APPROVAL",
            "accion": llamada["name"],
            "argumentos": llamada["args"]
        }
    
    return {"status": "COMPLETED", "respuesta": estado.values["messages"][-1].content}

@app.post("/chat/resume")
def resume_endpoint(payload: ResumeRequest):
    config = {"configurable": {"thread_id": payload.thread_id}}
    estado = graph.get_state(config)
    
    if "tools" not in estado.next:
        raise HTTPException(status_code=400, detail="No hay acciones pendientes en este hilo.")
        
    if payload.aprobado:
        # Caso 1: Aprobado -> continúa hacia el nodo "tools" normalmente
        resultado = graph.invoke(None, config=config)
        return {
            "status": "APPROVED_AND_EXECUTED",
            "respuesta": resultado["messages"][-1].content
        }

    # Caso 2: Rechazado
    # 1. Recuperamos la llamada pendiente que dejó el LLM
    ultimo_mensaje = estado.values["messages"][-1] # Va al último mensaje del historial, que es el que contiene la llamada a la tool, el nombre y el id
    llamada_pendiente = ultimo_mensaje.tool_calls[0]

    # 2. Creamos un ToolMessage simulando que la tool devolvió una cancelación
    mensaje_cancelacion = ToolMessage(
        content="Operación cancelada: El supervisor humano ha denegado la ejecución de esta acción.",
        tool_call_id=llamada_pendiente["id"],
        name=llamada_pendiente["name"]
    )

    # 3. Inyectamos este mensaje como si viniera del nodo 'tools'
    graph.update_state(config, {"messages": [mensaje_cancelacion]}, as_node="tools")
    
    # 4. Reanudamos el grafo para que el LLM lea la cancelación y cierre el turno
    resultado = graph.invoke(None, config=config)
    
    return {
        "status": "REJECTED",
        "respuesta": resultado["messages"][-1].content
    }
    