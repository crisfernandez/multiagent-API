from fastapi import FastAPI
from pydantic import BaseModel

from app.graph.agent import grafo

app = FastAPI(title="API Recomendador de Cine")


class ChatRequest(BaseModel):
    mensaje: str
    thread_id: str = "default"


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/chat")
def chat_endpoint(payload: ChatRequest):
    config = {"configurable": {"thread_id": payload.thread_id}}
    estado = grafo.invoke({"mensaje_usuario": payload.mensaje}, config=config)
    return {
        "status": "COMPLETED",
        "tipo_intencion": estado.get("tipo_intencion"),
        "termino_busqueda": estado.get("termino_busqueda"),
        "mood_detectado": estado.get("mood_detectado"),
        "keywords": estado.get("keywords", []),
        "respuesta": estado.get("respuesta_final"),
    }
