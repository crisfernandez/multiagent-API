from pathlib import Path
from typing import List

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.core.cache import CacheTTL
from app.core.tmdb import obtener_ficha
from app.graph.agent import grafo

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="API Recomendador de Cine")

# Caché única: guarda la salida del grafo (intención + pool + respuesta) por sesión.
# Evita repetir el LLM cuando el usuario refresca o repite la misma búsqueda.
_cache_grafo = CacheTTL(ttl_segundos=1800, max_items=512)
# Caché de la ficha en vivo de TMDB (evita reconsultar al hacer click).
_cache_ficha = CacheTTL(ttl_segundos=3600, max_items=256)

LIMITE_PAGINA = 10  # películas visibles por pantalla


class RecomendarRequest(BaseModel):
    mensaje: str = ""
    thread_id: str = "default"
    excluir_ids: List[int] = Field(default_factory=list)


def _resolver_estado(payload: RecomendarRequest) -> dict:
    """Ejecuta el grafo multiagente (o reutiliza su salida cacheada).

    El grafo es el motor: devuelve la intención, el pool de películas que buscó
    su ToolNode y la respuesta que redactó su nodo redactor.
    """
    clave = (payload.thread_id, payload.mensaje)
    cacheado = _cache_grafo.obtener(clave)
    if cacheado is not None:
        return cacheado

    config = {"configurable": {"thread_id": payload.thread_id}}
    estado = grafo.invoke({"mensaje_usuario": payload.mensaje}, config=config)
    salida = {
        "tipo_intencion": estado.get("tipo_intencion"),
        "termino_busqueda": estado.get("termino_busqueda"),
        "keywords": estado.get("keywords") or [],
        "mood_detectado": estado.get("mood_detectado"),
        "respuesta_final": estado.get("respuesta_final"),
        "respaldo_mood": estado.get("respaldo_mood", False),
        "peliculas": estado.get("peliculas") or [],
    }
    _cache_grafo.guardar(clave, salida)
    return salida


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/recomendar")
def recomendar(payload: RecomendarRequest):
    salida = _resolver_estado(payload)

    pool = salida.get("peliculas") or []
    excluidos = set(payload.excluir_ids or [])
    peliculas = [p for p in pool if p.get("id") not in excluidos][:LIMITE_PAGINA]

    return {
        "respuesta": salida.get("respuesta_final"),
        "intencion": {
            "tipo_intencion": salida.get("tipo_intencion"),
            "termino_busqueda": salida.get("termino_busqueda"),
            "keywords": salida.get("keywords"),
            "mood_detectado": salida.get("mood_detectado"),
        },
        "respaldo_mood": salida.get("respaldo_mood", False),
        "peliculas": peliculas,
    }


@app.get("/pelicula/{tmdb_id}")
def ficha_pelicula(tmdb_id: int):
    """Ficha completa consultada en vivo a TMDB, con caché."""
    ficha = _cache_ficha.obtener(tmdb_id)
    if ficha is not None:
        return ficha
    try:
        ficha = obtener_ficha(tmdb_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error))
    except Exception as error:  # red, TMDB caída, etc.
        raise HTTPException(status_code=502, detail=f"No se pudo consultar TMDB: {error}")
    _cache_ficha.guardar(tmdb_id, ficha)
    return ficha


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
