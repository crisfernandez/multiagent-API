"""Tests de la API delgada: paginación, caché y traducción de errores."""

from types import SimpleNamespace

from app import api


def _pool(cantidad):
    return [
        {"id": i, "tmdb_id": 100 + i, "titulo": f"Peli {i}", "nota": 5.0}
        for i in range(1, cantidad + 1)
    ]


def _estado(peliculas=None, **extra):
    base = {
        "tipo_intencion": "actor",
        "termino_busqueda": "Tom Hanks",
        "keywords": ["friendship"],
        "mood_detectado": None,
        "respuesta_final": "Respuesta del redactor",
        "respaldo_mood": False,
        "peliculas": peliculas if peliculas is not None else [],
    }
    base.update(extra)
    return base


def _instalar_grafo(monkeypatch, estado):
    llamadas = []

    def invoke(entrada, config):
        llamadas.append((entrada, config))
        return estado

    monkeypatch.setattr(api, "grafo", SimpleNamespace(invoke=invoke))
    return llamadas


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------


def test_health(client):
    respuesta = client.get("/health")

    assert respuesta.status_code == 200
    assert respuesta.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# /recomendar
# ---------------------------------------------------------------------------


def test_recomendar_pagina_el_pool_a_diez(client, monkeypatch):
    _instalar_grafo(monkeypatch, _estado(_pool(12)))

    respuesta = client.post(
        "/recomendar", json={"mensaje": "Tom Hanks", "thread_id": "hilo-1"}
    )

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert len(cuerpo["peliculas"]) == 10
    assert [p["id"] for p in cuerpo["peliculas"]] == list(range(1, 11))
    assert cuerpo["respuesta"] == "Respuesta del redactor"
    assert cuerpo["intencion"] == {
        "tipo_intencion": "actor",
        "termino_busqueda": "Tom Hanks",
        "keywords": ["friendship"],
        "mood_detectado": None,
    }
    assert cuerpo["respaldo_mood"] is False


def test_recomendar_excluye_ids_antes_de_paginar(client, monkeypatch):
    _instalar_grafo(monkeypatch, _estado(_pool(12)))

    respuesta = client.post(
        "/recomendar",
        json={"mensaje": "Tom Hanks", "thread_id": "hilo-1", "excluir_ids": [1, 2]},
    )

    ids = [p["id"] for p in respuesta.json()["peliculas"]]
    assert ids == list(range(3, 13))


def test_recomendar_completa_campos_ausentes(client, monkeypatch):
    _instalar_grafo(monkeypatch, {})

    respuesta = client.post("/recomendar", json={"mensaje": "hola"})

    cuerpo = respuesta.json()
    assert cuerpo["peliculas"] == []
    assert cuerpo["intencion"]["keywords"] == []
    assert cuerpo["intencion"]["tipo_intencion"] is None
    assert cuerpo["respaldo_mood"] is False


def test_recomendar_pasa_el_hilo_al_grafo(client, monkeypatch):
    llamadas = _instalar_grafo(monkeypatch, _estado())

    client.post("/recomendar", json={"mensaje": "Quiero comedia", "thread_id": "web-42"})

    entrada, config = llamadas[0]
    assert entrada == {"mensaje_usuario": "Quiero comedia"}
    assert config == {"configurable": {"thread_id": "web-42"}}


def test_recomendar_reutiliza_la_cache_por_hilo_y_mensaje(client, monkeypatch):
    llamadas = _instalar_grafo(monkeypatch, _estado(_pool(3)))

    client.post("/recomendar", json={"mensaje": "Tom Hanks", "thread_id": "hilo-1"})
    client.post("/recomendar", json={"mensaje": "Tom Hanks", "thread_id": "hilo-1"})
    assert len(llamadas) == 1

    client.post("/recomendar", json={"mensaje": "Otra cosa", "thread_id": "hilo-1"})
    assert len(llamadas) == 2

    client.post("/recomendar", json={"mensaje": "Tom Hanks", "thread_id": "hilo-2"})
    assert len(llamadas) == 3


# ---------------------------------------------------------------------------
# /pelicula/{tmdb_id}
# ---------------------------------------------------------------------------


def test_ficha_devuelve_datos_y_los_cachea(client, monkeypatch):
    llamadas = []

    def obtener_ficha(tmdb_id):
        llamadas.append(tmdb_id)
        return {"tmdb_id": tmdb_id, "titulo": "Origen"}

    monkeypatch.setattr(api, "obtener_ficha", obtener_ficha)

    primera = client.get("/pelicula/27205")
    segunda = client.get("/pelicula/27205")

    assert primera.status_code == 200
    assert primera.json() == {"tmdb_id": 27205, "titulo": "Origen"}
    assert segunda.json() == primera.json()
    assert llamadas == [27205]


def test_ficha_inexistente_devuelve_404(client, monkeypatch):
    def obtener_ficha(tmdb_id):
        raise ValueError("Película no encontrada")

    monkeypatch.setattr(api, "obtener_ficha", obtener_ficha)

    respuesta = client.get("/pelicula/999")

    assert respuesta.status_code == 404
    assert respuesta.json()["detail"] == "Película no encontrada"


def test_ficha_con_fallo_de_red_devuelve_502(client, monkeypatch):
    def obtener_ficha(tmdb_id):
        raise RuntimeError("TMDB caída")

    monkeypatch.setattr(api, "obtener_ficha", obtener_ficha)

    respuesta = client.get("/pelicula/1")

    assert respuesta.status_code == 502
    assert "TMDB caída" in respuesta.json()["detail"]


# ---------------------------------------------------------------------------
# Frontend estático
# ---------------------------------------------------------------------------


def test_index_sirve_el_html(client):
    respuesta = client.get("/")

    assert respuesta.status_code == 200
    assert "text/html" in respuesta.headers["content-type"]


def test_static_sirve_los_assets(client):
    respuesta = client.get("/static/styles.css")

    assert respuesta.status_code == 200
    assert "text/css" in respuesta.headers["content-type"]
