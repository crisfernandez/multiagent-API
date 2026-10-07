from typing import Annotated, List, Literal, Optional

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field
from typing_extensions import TypedDict


# 1. El molde del Router (Nodo 1)
class ClasificacionIntencion(BaseModel):
    tipo: Literal["actor", "genero", "mood"] = Field(
        description="Elige 'actor' si pide un intérprete, 'genero' si pide un género cinematográfico formal, o 'mood' si describe emociones, ideas o temas."
    )
    entidad: Optional[str] = Field(
        default=None,
        description="El nombre del actor o del género detectado (ej: 'Tom Hanks', 'Comedia'). Si es mood, deja None.",
    )


class EstadoRecomendador(TypedDict, total=False):
    mensaje_usuario: str  # Lo que escribe el usuario
    messages: Annotated[list[BaseMessage], add_messages]  # Historial para ToolNode
    mood_detectado: Optional[str]  # Breve resumen emocional (ej: "triste y estresado")
    tipo_intencion: Optional[Literal["actor", "genero", "mood"]]
    termino_busqueda: Optional[str]
    keywords: List[str]  # Lista de temas generados por el nodo psicólogo
    peliculas_encontradas: Optional[str]
    respuesta_final: Optional[str]  # Respuesta formateada con las 5 películas


# Clase para asegurar que el nodo que recibe el estado emocional del usuario no introduzca texto sobrante.
class AnalisisEmocional(BaseModel):
    mood_detectado: str = Field(description="Resumen corto del estado emocional detectado (ej: cansado, triste, motivado)")
    keywords: List[str] = Field(description="Lista de 2 a 3 palabras clave o conceptos cinematográficos temáticos para buscar")
