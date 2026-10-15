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
    tipo_intencion: Optional[Literal["actor", "genero", "mood", "titulo"]]
    termino_busqueda: Optional[str]
    keywords: List[str]  # Lista de temas (en inglés, p/ catálogo TMDB)
    generos_mood: List[str]  # Géneros en español que deduce el psicólogo del mood
    peliculas: List[dict]  # Pool estructurado que sale del ToolNode y alimenta la API
    ya_reintentado: bool  # Evita bucles infinitos en el reintento del agente buscador
    respaldo_mood: bool  # True si se usó el respaldo "lo mejor valorado"
    respuesta_final: Optional[str]  # Respuesta formateada por el nodo redactor


# Clase para asegurar que el nodo que recibe el estado emocional del usuario no introduzca texto sobrante.
class AnalisisEmocional(BaseModel):
    mood_detectado: str = Field(description="Resumen corto del estado emocional detectado (ej: cansado, triste, motivado)")
    generos: List[str] = Field(
        description=(
            "De esta lista exacta, elige 1 a 3 géneros que mejor encajen con el ánimo: "
            "Drama, Romántica, Comedia, Terror, Ciencia ficción, Thriller, Animación, Acción, Aventura"
        )
    )
    keywords: List[str] = Field(
        description=(
            "2 o 3 palabras clave EN INGLÉS para buscar en el catálogo de cine (tipo TMDB): "
            "conceptos descriptivos como friendship, vacation, feel good, revenge, survival. NO las traduzcas."
        )
    )
