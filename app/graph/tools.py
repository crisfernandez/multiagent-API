import json
from typing import List, Optional
import unicodedata

from langchain_core.tools import tool
from sqlalchemy import and_, desc, or_

from app.core.database import PeliculaDB, SessionLocal

TMDB_IMAGE_BASE_URL = "https://image.tmdb.org/t/p/w500"
SIN_RESULTADOS = "No se encontraron películas con esos criterios."


def _normalizar(valor: Optional[str]) -> str:
    """Pasa a minúsculas y quita acentos para comparar de forma flexible."""
    if not valor:
        return ""
    sin_acentos = unicodedata.normalize("NFKD", valor).encode("ascii", "ignore").decode("ascii")
    return sin_acentos.lower()


def _tokens(valor: str) -> List[str]:
    """Trocea 'Spider-Man: No Way Home' en palabras para un match flexible."""
    partes = [p for p in valor.replace(":", " ").replace("-", " ").split() if len(p) >= 2]
    return partes or [valor]


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


# El LLM a veces devuelve los géneros en inglés aunque se le pida la lista
# española. Este mapa los traduce a los valores exactos de la columna `generos`.
_GENEROS_EN_ESPANOL = {
    "action": "Acción",
    "accion": "Acción",
    "adventure": "Aventura",
    "aventura": "Aventura",
    "animation": "Animación",
    "animacion": "Animación",
    "comedy": "Comedia",
    "comedia": "Comedia",
    "drama": "Drama",
    "horror": "Terror",
    "terror": "Terror",
    "romance": "Romántica",
    "romantica": "Romántica",
    "romantic": "Romántica",
    "thriller": "Thriller",
    "sci-fi": "Ciencia ficción",
    "scifi": "Ciencia ficción",
    "science fiction": "Ciencia ficción",
    "ciencia ficcion": "Ciencia ficción",
    "ciencia ficción": "Ciencia ficción",
}


def _mapear_generos(generos: Optional[List[str]]) -> Optional[List[str]]:
    """Convierte los géneros del LLM a los valores en español del catálogo."""
    if not generos:
        return None
    mapeados = []
    for g in generos:
        clave = _normalizar(g)
        mapeados.append(_GENEROS_EN_ESPANOL.get(clave, g.strip()))
    return mapeados or None


def _listar(texto: Optional[str]) -> List[str]:
    """Convierte 'Drama, Acción' en ['Drama', 'Acción']."""
    if not texto:
        return []
    return [parte.strip() for parte in texto.split(",") if parte.strip()]


def _plataformas_limpias(texto: Optional[str]) -> List[str]:
    """Quita variantes ruidosas (con anuncios, 'Channel', duplicados)."""
    vistas = []
    for nombre in _listar(texto):
        if "with Ads" in nombre or nombre.endswith("Channel"):
            continue
        if nombre not in vistas:
            vistas.append(nombre)
    return vistas


def pelicula_a_dict(pelicula: PeliculaDB) -> dict:
    """Convierte un registro de la BD en el JSON que consume el frontend."""
    cartel = f"{TMDB_IMAGE_BASE_URL}{pelicula.poster_path}" if pelicula.poster_path else None
    return {
        "id": pelicula.id,
        "tmdb_id": pelicula.tmdb_id,
        "titulo": pelicula.titulo,
        "poster": cartel,
        "nota": round(pelicula.puntuacion, 1) if pelicula.puntuacion is not None else None,
        "director": pelicula.director,
        "anio": pelicula.anio,
        "sinopsis": pelicula.sinopsis,
        "generos": _listar(pelicula.generos),
        "reparto": _listar(pelicula.actores),
        "plataformas": _plataformas_limpias(pelicula.plataformas),
    }


@tool
def buscar_peliculas(
    actor: Optional[str] = None,
    genero: Optional[str] = None,
    generos: Optional[List[str]] = None,
    titulo: Optional[str] = None,
    keywords: Optional[List[str]] = None,
    limite: int = 60,
) -> str:
    """
    Busca en el catálogo interno de cine. Úsala SIEMPRE que necesites datos reales
    del catálogo (títulos, puntuaciones, carteles, reparto, plataformas) para
    responder al usuario; NO la uses para conversación general ni para pedir
    aclaraciones.

    Criterios (combinables entre sí; si no pasas ninguno devuelve el catálogo
    ordenado por puntuación):
    - actor: nombre de un intérprete (ej: "Tom Hanks"). También casa con títulos parecidos.
    - genero: un género en español (ej: "Comedia").
    - generos: lista de géneros en español para estados de ánimo (ej: ["Drama", "Thriller"]).
    - titulo: título concreto (ej: "Origen").
    - keywords: palabras clave en inglés del catálogo (ej: ["friendship", "revenge"]).
    - limite: nº máximo de películas a devolver (usa 60 para dejar margen de paginación).

    Devuelve un JSON con la forma
    {"sin_resultados": bool, "peliculas": [ {...}, ... ]}.
    """
    peliculas = consultar_peliculas(
        actor=actor,
        genero=genero,
        generos=generos,
        titulo=titulo,
        keywords=keywords,
        limite=limite,
    )
    return json.dumps(
        {
            "sin_resultados": not peliculas,
            "peliculas": [pelicula_a_dict(p) for p in peliculas],
        },
        ensure_ascii=False,
    )


def consultar_peliculas(
    actor: Optional[str] = None,
    genero: Optional[str] = None,
    generos: Optional[List[str]] = None,
    titulo: Optional[str] = None,
    keywords: Optional[List[str]] = None,
    limite: int = 10,
    excluir_ids: Optional[List[int]] = None,
) -> List[PeliculaDB]:
    """
    Devuelve objetos PeliculaDB (no texto) para que la API los serialice a JSON.

    Mantiene el mismo espíritu que buscar_peliculas, pero además permite buscar
    por título concreto (la entidad detectada por el agente puede ser un título)
    y excluir ids ya vistos para el botón de refrescar.
    """
    actor = _norm_termino(actor)
    genero = _norm_termino(genero)
    generos = _mapear_generos(_norm_keywords(generos))
    titulo = _norm_termino(titulo)
    keywords = _norm_keywords(keywords)

    db = SessionLocal()
    try:
        query = db.query(PeliculaDB)

        # Actor o, si en realidad el usuario escribió un título, por título.
        if actor:
            actor_tokens = _tokens(actor)
            query = query.filter(
                or_(
                    and_(*[PeliculaDB.actores.ilike(f"%{_escape_like(t)}%", escape="\\") for t in actor_tokens]),
                    and_(*[PeliculaDB.titulo.ilike(f"%{_escape_like(t)}%", escape="\\") for t in actor_tokens]),
                )
            )

        # Género o, si en realidad el usuario escribió un título, por título.
        if genero:
            genero_tokens = _tokens(genero)
            query = query.filter(
                or_(
                    and_(*[PeliculaDB.generos.ilike(f"%{_escape_like(t)}%", escape="\\") for t in genero_tokens]),
                    and_(*[PeliculaDB.titulo.ilike(f"%{_escape_like(t)}%", escape="\\") for t in genero_tokens]),
                )
            )

        # Búsqueda explícita por título (usada por la detección por catálogo).
        if titulo:
            titulo_tokens = _tokens(titulo)
            query = query.filter(
                and_(*[PeliculaDB.titulo.ilike(f"%{_escape_like(t)}%", escape="\\") for t in titulo_tokens])
            )

        # Criterios "suaves" del mood: géneros en español + keywords TMDB en inglés.
        # Se combinan con OR para maximizar resultados: cualquier coincidencia vale.
        condiciones_o = []
        for g in generos or []:
            condiciones_o.append(PeliculaDB.generos.ilike(f"%{_escape_like(g)}%", escape="\\"))
        for kw in keywords or []:
            kw_esc = _escape_like(kw)
            condiciones_o.append(PeliculaDB.keywords.ilike(f"%{kw_esc}%", escape="\\"))
            condiciones_o.append(PeliculaDB.sinopsis.ilike(f"%{kw_esc}%", escape="\\"))
        if condiciones_o:
            query = query.filter(or_(*condiciones_o))

        if excluir_ids:
            query = query.filter(~PeliculaDB.id.in_(excluir_ids))

        resultados = query.order_by(desc(PeliculaDB.puntuacion)).limit(limite).all()
        if resultados:
            return resultados

        # Respaldo sin acentos: si la búsqueda no encontró nada (p. ej. el
        # clasificador devuelve 'Ciencia ficcion' sin tilde), comparamos
        # normalizando los textos con un recorrido sencillo en Python.
        excluidos = set(excluir_ids or [])
        candidatos = []
        termino = actor or genero or titulo

        if termino:
            tokens = [_normalizar(t) for t in _tokens(termino)]
            for p in db.query(PeliculaDB).all():
                if p.id in excluidos:
                    continue
                heno = _normalizar(f"{p.titulo} {p.generos} {p.actores}")
                if all(t in heno for t in tokens):
                    candidatos.append(p)
        elif generos:
            # Mood: basta con que la película tenga ALGÚN género de la lista.
            generos_norm = [_normalizar(g) for g in generos]
            for p in db.query(PeliculaDB).all():
                if p.id in excluidos:
                    continue
                heno = _normalizar(p.generos)
                if any(g and g in heno for g in generos_norm):
                    candidatos.append(p)
        else:
            return []

        candidatos.sort(key=lambda p: p.puntuacion or 0, reverse=True)
        return candidatos[:limite]
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Detección de términos directamente contra el catálogo
#
# Sirve de red de seguridad cuando el enrutador del LLM falla (por ejemplo,
# "películas con Tom Hanks" clasificado como género). Busca géneros, títulos o
# actores reales dentro del propio mensaje. No usa el LLM.
# ---------------------------------------------------------------------------
_GENEROS_CATALOGO: Optional[List[str]] = None
_INDICE_NOMBRES: Optional[List[tuple]] = None


def _generos_catalogo() -> List[str]:
    global _GENEROS_CATALOGO
    if _GENEROS_CATALOGO is None:
        db = SessionLocal()
        try:
            nombres = set()
            for (genero,) in db.query(PeliculaDB.generos).distinct():
                for parte in (genero or "").split(","):
                    parte = parte.strip()
                    if parte:
                        nombres.add(parte)
        finally:
            db.close()
        # Los más largos primero para que "Ciencia ficción" gane a "Acción".
        _GENEROS_CATALOGO = sorted(nombres, key=len, reverse=True)
    return _GENEROS_CATALOGO


def _indice_nombres() -> List[tuple]:
    global _INDICE_NOMBRES
    if _INDICE_NOMBRES is None:
        db = SessionLocal()
        try:
            nombres = []
            for (actores,) in db.query(PeliculaDB.actores).distinct():
                for parte in (actores or "").split(","):
                    parte = parte.strip()
                    if parte:
                        nombres.append(("actor", parte))
            for (titulo,) in db.query(PeliculaDB.titulo).distinct():
                if titulo:
                    nombres.append(("titulo", titulo))
        finally:
            db.close()
        _INDICE_NOMBRES = [(tipo, nombre, _normalizar(nombre)) for tipo, nombre in nombres]
    return _INDICE_NOMBRES


def detectar_termino_catalogo(mensaje: str) -> Optional[dict]:
    """Devuelve {'tipo': 'genero'|'actor'|'titulo', 'termino': str} o None."""
    if not mensaje:
        return None
    texto = _normalizar(mensaje)

    for genero in _generos_catalogo():
        genero_norm = _normalizar(genero)
        if genero_norm and any(c.isalnum() for c in genero_norm) and genero_norm in texto:
            return {"tipo": "genero", "termino": genero}

    mejor = None
    for tipo, nombre, nombre_norm in _indice_nombres():
        # Exigimos al menos una letra/número: los títulos en scripts no latinos
        # (coreano, ruso, tamil...) se normalizan a un solo espacio y, sin esta
        # guarda, " " casaría con cualquier mensaje que lleve espacios.
        if not nombre_norm or not any(c.isalnum() for c in nombre_norm):
            continue
        if nombre_norm in texto:
            if mejor is None or len(nombre_norm) > len(mejor[2]):
                mejor = (tipo, nombre, nombre_norm)

    if mejor:
        return {"tipo": mejor[0], "termino": mejor[1]}
    return None
