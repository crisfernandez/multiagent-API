from sqlalchemy import Column, Float, Integer, String, Text, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from app.core.config import settings

# connect_args={"check_same_thread": False} es obligatorio para SQLite con FastAPI
engine = create_engine(
    settings.DATABASE_URL, connect_args={"check_same_thread": False}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


class PeliculaDB(Base):
    __tablename__ = "peliculas"

    id = Column(Integer, primary_key=True, index=True)
    tmdb_id = Column(Integer, unique=True, index=True)
    titulo = Column(String(255), index=True)
    sinopsis = Column(Text)
    generos = Column(String(255), index=True)  # Ej: "Drama, Ciencia ficción"
    actores = Column(String(500), index=True)  # Ej: "Leonardo DiCaprio, ..."
    keywords = Column(Text)  # Palabras clave de TMDB
    puntuacion = Column(Float)
    poster_path = Column(String(255), nullable=True)
    director = Column(String(255), nullable=True)  # Nombre del director/a
    anio = Column(Integer, nullable=True)  # Año de estreno
    plataformas = Column(String(255), nullable=True)  # Plataformas de streaming (ES)