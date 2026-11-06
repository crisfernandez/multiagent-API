"""Tests de la capa de búsqueda (`app/graph/tools.py`).

Aquí vive la lógica que más se rompe: tokens, acentos, OR del mood,
exclusión de ids y detección de términos contra el catálogo.
"""

import json
from types import SimpleNamespace

import pytest

from app.core.database import PeliculaDB
from app.graph import tools
from app.graph.tools import (
    _escape_like,
    _listar,
    _mapear_generos,
    _norm_keywords,
    _norm_termino,
    _normalizar,
    _plataformas_limpias,
    _tokens,
    buscar_peliculas,
    consultar_peliculas,
    detectar_termino_catalogo,
    pelicula_a_dict,
)


def _ids(resultados):
    return {p.tmdb_id for p in resultados}


def _id_de(fabrica_sesiones, tmdb_id):
    db = fabrica_sesiones()
    try:
        return db.query(tools.PeliculaDB).filter_by(tmdb_id=tmdb_id).one().id
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Helpers puros
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("valor", "esperado"),
    [
        ("Ciencia Ficción", "ciencia ficcion"),
        ("Penélope Cruz", "penelope cruz"),
        ("", ""),
        (None, ""),
    ],
)
def test_normalizar_quita_acentos_y_minusculas(valor, esperado):
    assert _normalizar(valor) == esperado


@pytest.mark.parametrize(
    ("valor", "esperado"),
    [
        ("Spider-Man: No Way Home", ["Spider", "Man", "No", "Way", "Home"]),
        ("Toy Story", ["Toy", "Story"]),
        ("A", ["A"]),
        ("  ", ["  "]),
    ],
)
def test_tokens_trocea_por_espacios_guiones_y_dos_puntos(valor, esperado):
    assert _tokens(valor) == esperado


def test_escape_like_escapa_comodines_y_barra():
    assert _escape_like(r"100%_x\y") == r"100\%\_x\\y"


@pytest.mark.parametrize(
    ("valor", "esperado"),
    [(None, None), ("   ", None), ("  Origen  ", "Origen")],
)
def test_norm_termino(valor, esperado):
    assert _norm_termino(valor) == esperado


@pytest.mark.parametrize(
    ("valor", "esperado"),
    [
        (None, None),
        ([], None),
        (["  ", ""], None),
        ([" a ", "", "b", "c", "d", "e", "f"], ["a", "b", "c", "d", "e"]),
    ],
)
def test_norm_keywords_limpia_y_limita_a_cinco(valor, esperado):
    assert _norm_keywords(valor) == esperado


@pytest.mark.parametrize(
    ("valor", "esperado"),
    [
        (None, None),
        (["Action", "ciencia ficcion", "Drama"], ["Acción", "Ciencia ficción", "Drama"]),
        (["SCI-FI"], ["Ciencia ficción"]),
        (["Musical"], ["Musical"]),
    ],
)
def test_mapear_generos_traduce_ingles_a_espanol(valor, esperado):
    assert _mapear_generos(valor) == esperado


@pytest.mark.parametrize(
    ("valor", "esperado"),
    [(None, []), ("", []), ("Drama, , Acción", ["Drama", "Acción"])],
)
def test_listar(valor, esperado):
    assert _listar(valor) == esperado


def test_plataformas_limpias_quita_ruido_y_duplicados():
    texto = "Netflix, Netflix with Ads, Netflix Channel, Prime Video, Netflix"

    assert _plataformas_limpias(texto) == ["Netflix", "Prime Video"]


@pytest.mark.parametrize(
    ("mensaje", "esperado"),
    [
        ("Busco una película de menos de 2 horas", 120),
        ("que dure máximo 90 minutos", 90),
        ("hasta 1 hora y media", 90),
        ("no más de 120 minutos", 120),
        ("menos de 1h 30m", 90),
        ("películas de Tom Hanks", None),
        ("", None),
    ],
)
def test_parsear_duracion_max(mensaje, esperado):
    assert tools.parsear_duracion_max(mensaje) == esperado


# ---------------------------------------------------------------------------
# Serialización
# ---------------------------------------------------------------------------


def test_pelicula_a_dict_serializa_todos_los_campos(fabrica_sesiones):
    db = fabrica_sesiones()
    try:
        pulp = db.query(tools.PeliculaDB).filter_by(tmdb_id=1).one()
        datos = pelicula_a_dict(pulp)
    finally:
        db.close()

    assert datos == {
        "id": pulp.id,
        "tmdb_id": 1,
        "titulo": "Pulp Fiction",
        "poster": "https://image.tmdb.org/t/p/w500/pulp.jpg",
        "nota": 8.9,
        "director": "Quentin Tarantino",
        "anio": 1994,
        "sinopsis": "Dos sicarios conversan antes de un trabajo.",
        "duracion": 154,
        "generos": ["Thriller", "Drama"],
        "reparto": ["John Travolta", "Samuel L. Jackson"],
        "plataformas": ["Netflix", "Prime Video"],
    }


def test_pelicula_a_dict_tolera_campos_nulos(fabrica_sesiones):
    db = fabrica_sesiones()
    try:
        vacia = db.query(tools.PeliculaDB).filter_by(tmdb_id=9).one()
        datos = pelicula_a_dict(vacia)
    finally:
        db.close()

    assert datos["poster"] is None
    assert datos["nota"] is None
    assert datos["generos"] == []
    assert datos["reparto"] == []
    assert datos["plataformas"] == []


def test_pelicula_a_dict_redondea_la_nota_y_tolera_duracion_nula():
    datos = pelicula_a_dict(SimpleNamespace(
        id=1,
        tmdb_id=1,
        titulo="Prueba",
        poster_path=None,
        puntuacion=7.06,
        director=None,
        anio=None,
        sinopsis=None,
        duracion=None,
        generos=None,
        actores=None,
        plataformas=None,
    ))

    assert datos["nota"] == 7.1
    assert datos["duracion"] is None


# ---------------------------------------------------------------------------
# Tool pública (contrato JSON que consume el ToolNode)
# ---------------------------------------------------------------------------


def test_buscar_peliculas_devuelve_json_con_resultados():
    crudo = buscar_peliculas.invoke({"actor": "Tom Hanks"})
    datos = json.loads(crudo)

    assert datos["sin_resultados"] is False
    assert {p["tmdb_id"] for p in datos["peliculas"]} == {2, 6}
    assert all("Tom Hanks" in p["reparto"] for p in datos["peliculas"])


def test_buscar_peliculas_marca_sin_resultados():
    datos = json.loads(buscar_peliculas.invoke({"actor": "Nadie Inexistente"}))

    assert datos == {"sin_resultados": True, "peliculas": []}


# ---------------------------------------------------------------------------
# consultar_peliculas: cada criterio por separado
# ---------------------------------------------------------------------------


def test_consultar_por_actor_compartido():
    assert _ids(consultar_peliculas(actor="Tom Hanks")) == {2, 6}


def test_consultar_actor_cae_a_titulo_si_no_es_un_actor():
    assert _ids(consultar_peliculas(actor="Forrest Gump")) == {2}


def test_consultar_por_genero():
    assert _ids(consultar_peliculas(genero="Comedia")) == {6}


def test_consultar_genero_cae_a_titulo():
    assert _ids(consultar_peliculas(genero="Toy Story")) == {6}


def test_consultar_por_titulo_exacto():
    assert _ids(consultar_peliculas(titulo="Spider-Man: No Way Home")) == {7}


def test_consultar_por_titulo_parcial_con_tokens():
    assert _ids(consultar_peliculas(titulo="Spider")) == {7}


def test_consultar_varios_generos_combina_con_or():
    ids = _ids(consultar_peliculas(generos=["Drama", "Romántica"]))

    assert {1, 2, 3, 8}.issubset(ids)


def test_consultar_mapea_generos_en_ingles_del_llm():
    assert _ids(consultar_peliculas(generos=["Action"])) == {4, 7}


def test_consultar_por_keyword():
    assert _ids(consultar_peliculas(keywords=["friendship"])) == {2, 6}


def test_consultar_por_keyword_en_sinopsis():
    assert _ids(consultar_peliculas(keywords=["space"])) == {3}


def test_consultar_sin_coincidencias_devuelve_vacio():
    assert consultar_peliculas(generos=["Musical"], keywords=["zzz_no_existe"]) == []


def test_consultar_actor_inexistente_devuelve_vacio():
    assert consultar_peliculas(actor="xyz") == []


# ---------------------------------------------------------------------------
# consultar_peliculas: orden, límite y exclusión
# ---------------------------------------------------------------------------


def test_consultar_sin_criterios_ordena_por_nota_y_respeta_limite():
    resultados = consultar_peliculas(limite=1)

    assert [p.tmdb_id for p in resultados] == [1]


def test_consultar_ordena_de_mayor_a_menor_nota():
    notas = [p.puntuacion for p in consultar_peliculas(generos=["Drama"])]

    assert notas == sorted(notas, reverse=True)


def test_consultar_excluye_ids_ya_vistos(fabrica_sesiones):
    forrest = _id_de(fabrica_sesiones, 2)

    resultados = consultar_peliculas(actor="Tom Hanks", excluir_ids=[forrest])

    assert _ids(resultados) == {6}


def test_consultar_excluye_ids_tambien_en_el_respaldo_sin_acentos(fabrica_sesiones):
    origen = _id_de(fabrica_sesiones, 4)

    resultados = consultar_peliculas(genero="Ciencia ficcion", excluir_ids=[origen])

    assert _ids(resultados) == {3}


def test_consultar_sin_criterios_devuelve_todo_el_catalogo():
    assert len(consultar_peliculas(limite=100)) == 9


def test_cumple_duracion_rechaza_sin_dato_y_excedida():
    assert tools._cumple_duracion(SimpleNamespace(duracion=90), 120) is True
    assert tools._cumple_duracion(SimpleNamespace(duracion=148), 120) is False
    assert tools._cumple_duracion(SimpleNamespace(duracion=None), 120) is False


def test_consultar_filtra_por_duracion_maxima():
    assert _ids(consultar_peliculas(duracion_max=120)) == {6, 8}


def test_consultar_combina_duracion_con_actor():
    assert _ids(consultar_peliculas(actor="Tom Hanks", duracion_max=100)) == {6}


def test_consultar_duracion_excluye_peliculas_sin_dato():
    assert 9 not in _ids(consultar_peliculas(duracion_max=1000))


def test_consultar_duracion_tambien_en_el_respaldo_sin_acentos(monkeypatch):
    monkeypatch.setattr(tools, "_GENEROS_EN_ESPANOL", {})

    assert _ids(consultar_peliculas(generos=["Drama"], duracion_max=100)) == {8}


def test_buscar_peliculas_filtra_por_duracion_y_la_expone():
    datos = json.loads(
        buscar_peliculas.invoke({"generos": ["Drama"], "duracion_max": 100})
    )

    assert {p["tmdb_id"] for p in datos["peliculas"]} == {8}
    assert datos["peliculas"][0]["duracion"] == 96


def test_pelicula_db_persiste_la_duracion(fabrica_sesiones):
    db = fabrica_sesiones()
    try:
        pelicula = PeliculaDB(tmdb_id=99, titulo="Prueba", duracion=90)
        db.add(pelicula)
        db.commit()
        db.refresh(pelicula)
    finally:
        db.close()

    assert pelicula.duracion == 90


# ---------------------------------------------------------------------------
# Respaldo sin acentos
# ---------------------------------------------------------------------------


def test_consultar_respaldo_sin_acentos_encuentra_ciencia_ficcion():
    assert _ids(consultar_peliculas(genero="Ciencia ficcion")) == {3, 4}


def test_consultar_respaldo_sin_acentos_con_actor():
    assert _ids(consultar_peliculas(actor="Penelope Cruz")) == {8}


# ---------------------------------------------------------------------------
# detectar_termino_catalogo (red de seguridad del router)
# ---------------------------------------------------------------------------


def test_detectar_genero_con_acentos():
    assert detectar_termino_catalogo("Quiero ver ciencia ficción") == {
        "tipo": "genero",
        "termino": "Ciencia ficción",
    }


def test_detectar_actor():
    assert detectar_termino_catalogo("Películas con Tom Hanks") == {
        "tipo": "actor",
        "termino": "Tom Hanks",
    }


def test_detectar_titulo():
    assert detectar_termino_catalogo("Ponme Spider-Man: No Way Home") == {
        "tipo": "titulo",
        "termino": "Spider-Man: No Way Home",
    }


def test_detectar_prioriza_genero_sobre_actor():
    assert detectar_termino_catalogo("Me gusta la acción de Tom Hanks") == {
        "tipo": "genero",
        "termino": "Acción",
    }


def test_detectar_sin_mensaje_devuelve_none():
    assert detectar_termino_catalogo("") is None


def test_detectar_mensaje_generico_devuelve_none():
    assert detectar_termino_catalogo("hola, ¿qué tal?") is None


def test_detectar_ignora_titulos_no_latinos(monkeypatch):
    monkeypatch.setattr(tools, "_generos_catalogo", lambda: [])
    monkeypatch.setattr(tools, "_indice_nombres", lambda: [("titulo", "영화", "")])

    assert detectar_termino_catalogo("hola mundo") is None


def test_consultar_mood_sin_tilde_usa_el_respaldo_en_python(
    monkeypatch, fabrica_sesiones
):
    monkeypatch.setattr(tools, "_GENEROS_EN_ESPANOL", {})

    resultados = tools.consultar_peliculas(generos=["Ciencia ficcion"])

    assert {p.titulo for p in resultados} == {"Interstellar", "Origen"}


def test_consultar_mood_respeta_excluir_ids_en_el_respaldo(
    monkeypatch, fabrica_sesiones
):
    monkeypatch.setattr(tools, "_GENEROS_EN_ESPANOL", {})
    interstellar = _id_de(fabrica_sesiones, 3)

    resultados = tools.consultar_peliculas(
        generos=["Ciencia ficcion"], excluir_ids=[interstellar]
    )

    assert [p.titulo for p in resultados] == ["Origen"]


def test_consultar_con_catalogo_vacio_devuelve_lista(fabrica_sesiones):
    db = fabrica_sesiones()
    db.query(PeliculaDB).delete()
    db.commit()
    db.close()

    assert tools.consultar_peliculas() == []
