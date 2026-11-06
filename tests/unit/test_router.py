from types import SimpleNamespace

import pytest

from app.graph import agent
from app.graph.agent import ClasificacionIntencion


def _fake_router(monkeypatch, clasificacion):
    monkeypatch.setattr(
        agent,
        "llm_router",
        SimpleNamespace(invoke=lambda prompt: clasificacion),
    )


@pytest.mark.parametrize(
    ("tipo", "esperado"),
    [
        ("mood", "analizar_mood"),
        ("actor", "agente"),
        ("genero", "agente"),
        ("titulo", "agente"),
        (None, "pedir_aclaracion"),
    ],
)
def test_bifurcar_segun_intencion(tipo, esperado):
    state = {"tipo_intencion": tipo}

    resultado = agent.bifurcar_segun_intencion(state)

    assert resultado == esperado


def test_agente_envia_a_tools_si_hay_tool_calls():
    state = {
        "messages": [
            SimpleNamespace(tool_calls=[{"name": "buscar_peliculas"}])
        ]
    }

    resultado = agent.bifurcar_tras_agente(state)

    assert resultado == "tools"


def test_agente_redacta_si_ya_hay_peliculas(monkeypatch):
    monkeypatch.setattr(
        agent,
        "detectar_termino_catalogo",
        lambda mensaje: None,
    )

    state = {
        "messages": [SimpleNamespace(tool_calls=[])],
        "peliculas": [{"titulo": "Interstellar"}],
        "ya_reintentado": False,
    }

    resultado = agent.bifurcar_tras_agente(state)

    assert resultado == "redactar"


def test_agente_usa_respaldo_si_es_mood_y_no_hay_resultados(monkeypatch):
    monkeypatch.setattr(
        agent,
        "detectar_termino_catalogo",
        lambda mensaje: None,
    )

    state = {
        "messages": [SimpleNamespace(tool_calls=[])],
        "tipo_intencion": "mood",
        "peliculas": [],
        "ya_reintentado": False,
    }

    resultado = agent.bifurcar_tras_agente(state)

    assert resultado == "respaldo_mood"


def test_agente_reintenta_si_hay_actor_y_termino(monkeypatch):
    monkeypatch.setattr(
        agent,
        "detectar_termino_catalogo",
        lambda mensaje: None,
    )

    state = {
        "messages": [SimpleNamespace(tool_calls=[])],
        "mensaje_usuario": "Películas de Tom Hanks",
        "tipo_intencion": "actor",
        "termino_busqueda": "Tom Hanks",
        "peliculas": [],
        "ya_reintentado": False,
    }

    resultado = agent.bifurcar_tras_agente(state)

    assert resultado == "reintentar_catalogo"


def test_agente_redacta_si_no_hay_ninguna_accion_pendiente(monkeypatch):
    monkeypatch.setattr(
        agent,
        "detectar_termino_catalogo",
        lambda mensaje: None,
    )

    state = {
        "messages": [SimpleNamespace(tool_calls=[])],
        "tipo_intencion": None,
        "peliculas": [],
        "ya_reintentado": False,
    }

    resultado = agent.bifurcar_tras_agente(state)

    assert resultado == "redactar"

def test_router_clasifica_actor(monkeypatch):
    _fake_router(
        monkeypatch,
        ClasificacionIntencion(tipo="actor", entidad="Tom Hanks"),
    )

    state = {
        "mensaje_usuario": "Quiero películas de Tom Hanks"
    }

    resultado = agent.nodo_router(state)

    assert resultado["tipo_intencion"] == "actor"
    assert resultado["termino_busqueda"] == "Tom Hanks"


def test_router_clasifica_mood(monkeypatch):
    _fake_router(
        monkeypatch,
        ClasificacionIntencion(tipo="mood", entidad=None),
    )

    state = {
        "mensaje_usuario": "Necesito una película para animarme"
    }

    resultado = agent.nodo_router(state)

    assert resultado["tipo_intencion"] == "mood"
    assert resultado["termino_busqueda"] is None


def test_router_limpia_espacios_entidad(monkeypatch):
    _fake_router(
        monkeypatch,
        ClasificacionIntencion(tipo="genero", entidad="  Comedia  "),
    )

    state = {
        "mensaje_usuario": "Quiero comedias"
    }

    resultado = agent.nodo_router(state)

    assert resultado["termino_busqueda"] == "Comedia"


def test_router_extrae_la_duracion_maxima_del_mensaje(monkeypatch):
    _fake_router(
        monkeypatch,
        ClasificacionIntencion(tipo="actor", entidad="Tom Hanks"),
    )

    state = {
        "mensaje_usuario": "Películas de Tom Hanks que duren menos de 2 horas"
    }

    resultado = agent.nodo_router(state)

    assert resultado["duracion_max"] == 120


def test_router_limpia_estado_anterior(monkeypatch):
    _fake_router(
        monkeypatch,
        ClasificacionIntencion(tipo="actor", entidad="Tom Hanks"),
    )

    state = {
        "mensaje_usuario": "Películas de Tom Hanks",
        "peliculas": [{"titulo": "Anterior"}],
        "ya_reintentado": True,
        "respaldo_mood": True,
        "respuesta_final": "Respuesta anterior",
        "duracion_max": 150,
    }

    resultado = agent.nodo_router(state)

    assert resultado["duracion_max"] is None
    assert resultado["peliculas"] == []
    assert resultado["ya_reintentado"] is False
    assert resultado["respaldo_mood"] is False
    assert resultado["respuesta_final"] is None