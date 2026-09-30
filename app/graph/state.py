from sqlalchemy import Column, Integer, String, Text, Float
from app.core.database import Base

class PeliculaDB(Base):
    __tablename__ = "peliculas"

    id = Column(Integer, primary_key=True, index=True)
    tmdb_id = Column(Integer, unique=True, index=True)
    titulo = Column(String(255), index=True)
    sinopsis = Column(Text)
    generos = Column(String(255), index=True)     # Ej: "Drama, Ciencia ficción"
    actores = Column(String(500))                  # Ej: "Leonardo DiCaprio, Joseph Gordon-Levitt"
    keywords = Column(Text)                        # Palabras clave de TMDB
    puntuacion = Column(Float)
    poster_path = Column(String(255), nullable=True)