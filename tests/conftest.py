"""Fixtures compartidas por toda la suite.

Objetivo: que cada test sea rápido, determinista y no dependa de Ollama,
de TMDB ni de la base de datos real (`cine.db`). Todo se sustituye por
dobles locales que viven solo durante el test.
"""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import api
from app.core.cache import CacheTTL
from app.core.database import Base, PeliculaDB
from app.graph import agent, tools


# Catálogo mínimo para los tests. Cubre los casos que más nos interesan:
# acentos, varios géneros por película, un actor compartido, keywords en
# inglés, póster/puntuación nulos y plataformas con ruido.
PELICULAS = [
    {
        "tmdb_id": 1,
        "titulo": "Pulp Fiction",
        "sinopsis": "Dos sicarios conversan antes de un trabajo.",
        "duracion": 154,
        "generos": "Thriller, Drama",
        "actores": "John Travolta, Samuel L. Jackson",
        "keywords": "revenge, crime",
        "puntuacion": 8.9,
        "poster_path": "/pulp.jpg",
        "director": "Quentin Tarantino",
        "anio": 1994,
        "plataformas": "Netflix, Netflix with Ads, Prime Video",
    },
    {
        "tmdb_id": 2,
        "titulo": "Forrest Gump",
        "sinopsis": "Un hombre de buen corazón recorre la historia de su país.",
        "duracion": 142,
        "generos": "Drama, Romántica",
        "actores": "Tom Hanks, Robin Wright",
        "keywords": "friendship, feel good",
        "puntuacion": 8.8,
        "poster_path": "/forrest.jpg",
        "director": "Robert Zemeckis",
        "anio": 1994,
        "plataformas": "Netflix, Netflix Channel",
    },
    {
        "tmdb_id": 3,
        "titulo": "Interstellar",
        "sinopsis": "Un viaje espacial para salvar a la humanidad.",
        "duracion": 169,
        "generos": "Ciencia ficción, Drama",
        "actores": "Matthew McConaughey, Anne Hathaway",
        "keywords": "space, survival",
        "puntuacion": 8.7,
        "poster_path": "/inter.jpg",
        "director": "Christopher Nolan",
        "anio": 2014,
        "plataformas": "Prime Video, Prime Video with Ads",
    },
    {
        "tmdb_id": 4,
        "titulo": "Origen",
        "sinopsis": "Ladrones que entran en los sueños de otras personas.",
        "duracion": 148,
        "generos": "Ciencia ficción, Acción",
        "actores": "Leonardo DiCaprio, Elliot Page",
        "keywords": "dream, heist",
        "puntuacion": 8.4,
        "poster_path": "/origen.jpg",
        "director": "Christopher Nolan",
        "anio": 2010,
        "plataformas": "Netflix",
    },
    {
        "tmdb_id": 5,
        "titulo": "El resplandor",
        "sinopsis": "Un hotel aislado y una familia al borde de la locura.",
        "duracion": 146,
        "generos": "Terror, Thriller",
        "actores": "Jack Nicholson, Shelley Duvall",
        "keywords": "isolation, madness",
        "puntuacion": 8.4,
        "poster_path": None,
        "director": "Stanley Kubrick",
        "anio": 1980,
        "plataformas": "Max, Max with Ads",
    },
    {
        "tmdb_id": 6,
        "titulo": "Toy Story",
        "sinopsis": "Los juguetes de un niño cobran vida.",
        "duracion": 81,
        "generos": "Animación, Comedia, Aventura",
        "actores": "Tom Hanks, Tim Allen",
        "keywords": "friendship, toys",
        "puntuacion": 8.3,
        "poster_path": "/toy.jpg",
        "director": "John Lasseter",
        "anio": 1995,
        "plataformas": "Disney Plus",
    },
    {
        "tmdb_id": 7,
        "titulo": "Spider-Man: No Way Home",
        "sinopsis": "El multiverso se abre y los villanos regresan.",
        "duracion": 148,
        "generos": "Acción, Aventura",
        "actores": "Tom Holland, Zendaya",
        "keywords": "multiverse, superhero",
        "puntuacion": 8.2,
        "poster_path": "/spider.jpg",
        "director": "Jon Watts",
        "anio": 2021,
        "plataformas": "Netflix, Netflix with Ads",
    },
    {
        "tmdb_id": 8,
        "titulo": "Vicky Cristina Barcelona",
        "sinopsis": "Dos turistas se enamoran del mismo artista.",
        "duracion": 96,
        "generos": "Romántica, Drama",
        "actores": "Penélope Cruz, Scarlett Johansson",
        "keywords": "love, vacation",
        "puntuacion": 7.1,
        "poster_path": "/vicky.jpg",
        "director": "Woody Allen",
        "anio": 2008,
        "plataformas": None,
    },
    {
        "tmdb_id": 9,
        "titulo": "Película sin datos",
        "sinopsis": None,
        "duracion": None,
        "generos": None,
        "actores": None,
        "keywords": None,
        "puntuacion": None,
        "poster_path": None,
        "director": None,
        "anio": None,
        "plataformas": None,
    },
]


class FakeLLM:
    """Doble mínimo de un chat model.

    Acepta una respuesta fija, una lista de respuestas que se consumen en orden
    (la última se repite) o una función que recibe el prompt y decide.
    """

    def __init__(self, respuestas=None, funcion=None):
        self.respuestas = list(respuestas) if isinstance(respuestas, list) else [respuestas]
        self.funcion = funcion
        self.llamadas = []

    def invoke(self, entrada):
        self.llamadas.append(entrada)
        if self.funcion is not None:
            return self.funcion(entrada)
        if not self.respuestas or self.respuestas == [None]:
            raise AssertionError("FakeLLM.invoke llamado sin respuestas configuradas")
        if len(self.respuestas) == 1:
            return self.respuestas[0]
        return self.respuestas.pop(0)


@pytest.fixture
def fabrica_sesiones():
    """SQLite en memoria compartido por todas las conexiones del test."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    db = Session()
    db.add_all([PeliculaDB(**datos) for datos in PELICULAS])
    db.commit()
    db.close()

    yield Session
    engine.dispose()


@pytest.fixture(autouse=True)
def aislar_entorno(monkeypatch, fabrica_sesiones):
    """Sustituye la BD real y limpia las cachés globales de `tools`."""
    monkeypatch.setattr(tools, "SessionLocal", fabrica_sesiones)
    monkeypatch.setattr(tools, "_GENEROS_CATALOGO", None)
    monkeypatch.setattr(tools, "_INDICE_NOMBRES", None)
    yield


@pytest.fixture
def fakes(monkeypatch):
    """Instala dobles en los cuatro modelos del grafo y los devuelve."""
    router = FakeLLM()
    psicologo = FakeLLM()
    agente = FakeLLM()
    redactor = FakeLLM()
    monkeypatch.setattr(agent, "llm_router", router)
    monkeypatch.setattr(agent, "llm_psicologo", psicologo)
    monkeypatch.setattr(agent, "llm_agente", agente)
    monkeypatch.setattr(agent, "llm", redactor)
    return SimpleNamespace(
        router=router,
        psicologo=psicologo,
        agente=agente,
        redactor=redactor,
    )


@pytest.fixture
def client(monkeypatch):
    """TestClient con cachés nuevas para que no se filtren entre tests."""
    monkeypatch.setattr(api, "_cache_grafo", CacheTTL(ttl_segundos=1800, max_items=512))
    monkeypatch.setattr(api, "_cache_ficha", CacheTTL(ttl_segundos=3600, max_items=256))
    with TestClient(api.app) as cliente:
        yield cliente
