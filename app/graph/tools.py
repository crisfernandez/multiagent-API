from typing import List, Optional

from langchain_core.tools import tool
from sqlalchemy import desc, or_

from app.core.database import PeliculaDB, SessionLocal

TMDB_IMAGE_BASE_URL = "https://image.tmdb.org/t/p/w500"
SIN_RESULTADOS = "No se encontraron películas con esos criterios."


def _escape_like(valor: str) -> str:
    return valor.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _norm_termino(valor: Optional[str]) -> Optional[str]:
    if valor is None:
        return None
    limpio = valor.strip()
    return limpio or None


def _norm_keywords(keywords: Optional[List[str]]) -> Optional[List[str]]:
    if not keywords:
        return None
    limpias = [_norm_termino(kw) for kw in keywords]
    limpias = [kw for kw in limpias if kw][:5]
    return limpias or None


@tool
def buscar_peliculas(
    actor: Optional[str] = None,
    genero: Optional[str] = None,
    keywords: Optional[List[str]] = None,
    limite: int = 5,
) -> str:
    """
    Busca películas en la base de datos aplicando filtros opcionales por actor,
    género o lista de palabras clave temáticas.
    """
    actor = _norm_termino(actor)
    genero = _norm_termino(genero)
    keywords = _norm_keywords(keywords)

    db = SessionLocal()
    try:
        query = db.query(PeliculaDB)

        # 1. Filtro por Actor
        if actor:
            query = query.filter(PeliculaDB.actores.ilike(f"%{_escape_like(actor)}%", escape="\\"))

        # 2. Filtro por Género
        if genero:
            query = query.filter(PeliculaDB.generos.ilike(f"%{_escape_like(genero)}%", escape="\\"))

        # 3. Filtro por Keywords (en keywords O sinopsis)
        if keywords:
            condiciones = []
            for kw in keywords:
                kw_esc = _escape_like(kw)
                condiciones.append(PeliculaDB.keywords.ilike(f"%{kw_esc}%", escape="\\"))
                condiciones.append(PeliculaDB.sinopsis.ilike(f"%{kw_esc}%", escape="\\"))
            query = query.filter(or_(*condiciones))

        # Ordenar por mejor valoradas y limitar
        peliculas = query.order_by(desc(PeliculaDB.puntuacion)).limit(limite).all()

        if not peliculas:
            return SIN_RESULTADOS

        # Formatear el resultado como texto para el redactor
        resultado = []
        for p in peliculas:
            cartel = f"{TMDB_IMAGE_BASE_URL}{p.poster_path}" if p.poster_path else "Sin imagen disponible"
            sinopsis = (p.sinopsis or "")[:150]
            resultado.append(
                f"- Título: {p.titulo} | Nota: {p.puntuacion} | Póster: {cartel}\n"
                f"  Sinopsis: {sinopsis}..."
            )
        return "\n\n".join(resultado)

    finally:
        db.close()
