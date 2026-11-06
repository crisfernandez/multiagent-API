"""Tests de los nodos deterministas que rodean al agente.

`extraer_resultados` traduce el ToolMessage a `peliculas`, y los dos
fallbacks construyen un tool_call cuando el LLM decide no buscar.
"""

import json

import pytest
from langchain_core.messages import HumanMessage, ToolMessage

from app.graph import agent


def _tool_message(contenido):
    return ToolMessage(content=contenido, tool_call_id="call-1")


# ---------------------------------------------------------------------------
# nodo_extraer_resultados
# ---------------------------------------------------------------------------


def test_extraer_resultados_lee_json_del_ultimo_tool_message():
    state = {
        "messages": [
            HumanMessage(content="Busca algo"),
            _tool_message(json.dumps({"sin_resultados": False, "peliculas": [{"id": 1}]})),
        ]
    }

    assert agent.nodo_extraer_resultados(state) == {"peliculas": [{"id": 1}]}


def test_extraer_resultados_acepta_contenido_dict():
    mensaje = _tool_message("texto")
    mensaje.content = {"peliculas": [{"id": 2}]}

    assert agent.nodo_extraer_resultados({"messages": [mensaje]}) == {
        "peliculas": [{"id": 2}]
    }


def test_extraer_resultados_usa_el_ultimo_tool_message():
    state = {
        "messages": [
            _tool_message(json.dumps({"peliculas": [{"id": 1}]})),
            _tool_message(json.dumps({"peliculas": [{"id": 3}]})),
        ]
    }

    assert agent.nodo_extraer_resultados(state) == {"peliculas": [{"id": 3}]}


@pytest.mark.parametrize(
    "mensaje",
    [
        _tool_message("esto no es json"),
        _tool_message(json.dumps({"sin_resultados": True})),
        _tool_message(json.dumps({"peliculas": None})),
        _tool_message(json.dumps([])),
    ],
)
def test_extraer_resultados_devuelve_vacio_ante_datos_invalidos(mensaje):
    assert agent.nodo_extraer_resultados({"messages": [mensaje]}) == {"peliculas": []}


def test_extraer_resultados_filtra_por_duracion_maxima():
    state = {
        "duracion_max": 120,
        "messages": [
            _tool_message(
                json.dumps(
                    {
                        "peliculas": [
                            {"id": 1, "duracion": 90},
                            {"id": 2, "duracion": 148},
                            {"id": 3, "duracion": None},
                        ]
                    }
                )
            )
        ],
    }

    assert agent.nodo_extraer_resultados(state) == {
        "peliculas": [{"id": 1, "duracion": 90}]
    }


def test_extraer_resultados_sin_tool_message_devuelve_vacio():
    state = {"messages": [HumanMessage(content="hola")]}

    assert agent.nodo_extraer_resultados(state) == {"peliculas": []}


def test_extraer_resultados_sin_mensajes_devuelve_vacio():
    assert agent.nodo_extraer_resultados({}) == {"peliculas": []}


# ---------------------------------------------------------------------------
# nodo_reintentar_catalogo
# ---------------------------------------------------------------------------


def test_reintentar_prioriza_la_heuristica_del_catalogo(monkeypatch):
    monkeypatch.setattr(
        agent,
        "detectar_termino_catalogo",
        lambda mensaje: {"tipo": "actor", "termino": "Tom Hanks"},
    )

    resultado = agent.nodo_reintentar_catalogo(
        {
            "mensaje_usuario": "Películas con Tom Hanks",
            "tipo_intencion": "genero",
            "termino_busqueda": "Comedia",
        }
    )

    assert resultado["ya_reintentado"] is True
    assert resultado["tipo_intencion"] == "actor"
    assert resultado["termino_busqueda"] == "Tom Hanks"
    llamada = resultado["messages"][0]
    assert llamada.tool_calls[0]["name"] == "buscar_peliculas"
    assert llamada.tool_calls[0]["args"] == {
        "limite": agent.LIMITE_POOL,
        "actor": "Tom Hanks",
    }


@pytest.mark.parametrize(
    ("tipo", "termino", "clave"),
    [
        ("genero", "Comedia", "genero"),
        ("titulo", "Origen", "titulo"),
        ("actor", "Tom Hanks", "actor"),
    ],
)
def test_reintentar_usa_el_termino_del_router_si_no_hay_heuristica(
    monkeypatch, tipo, termino, clave
):
    monkeypatch.setattr(agent, "detectar_termino_catalogo", lambda mensaje: None)

    resultado = agent.nodo_reintentar_catalogo(
        {
            "mensaje_usuario": "consulta",
            "tipo_intencion": tipo,
            "termino_busqueda": termino,
        }
    )

    assert resultado["messages"][0].tool_calls[0]["args"] == {
        "limite": agent.LIMITE_POOL,
        clave: termino,
    }


@pytest.mark.parametrize(
    ("tipo", "termino"),
    [("mood", None), ("actor", None), (None, None)],
)
def test_reintentar_sin_termino_solo_pone_limite(monkeypatch, tipo, termino):
    monkeypatch.setattr(agent, "detectar_termino_catalogo", lambda mensaje: None)

    resultado = agent.nodo_reintentar_catalogo(
        {
            "mensaje_usuario": "consulta",
            "tipo_intencion": tipo,
            "termino_busqueda": termino,
        }
    )

    assert resultado["messages"][0].tool_calls[0]["args"] == {
        "limite": agent.LIMITE_POOL
    }


def test_reintentar_propaga_la_duracion_maxima(monkeypatch):
    monkeypatch.setattr(agent, "detectar_termino_catalogo", lambda mensaje: None)

    resultado = agent.nodo_reintentar_catalogo(
        {
            "mensaje_usuario": "Películas de Tom Hanks de menos de 2 horas",
            "tipo_intencion": "actor",
            "termino_busqueda": "Tom Hanks",
            "duracion_max": 120,
        }
    )

    assert resultado["messages"][0].tool_calls[0]["args"] == {
        "limite": agent.LIMITE_POOL,
        "actor": "Tom Hanks",
        "duracion_max": 120,
    }


# ---------------------------------------------------------------------------
# nodo_respaldo_mood
# ---------------------------------------------------------------------------


def test_respaldo_mood_pide_el_catalogo_sin_filtros():
    resultado = agent.nodo_respaldo_mood({})

    assert resultado["ya_reintentado"] is True
    assert resultado["respaldo_mood"] is True
    llamada = resultado["messages"][0]
    assert llamada.tool_calls[0]["name"] == "buscar_peliculas"
    assert llamada.tool_calls[0]["args"] == {"limite": agent.LIMITE_POOL}
    assert llamada.tool_calls[0]["id"].startswith("respaldo-")


def test_respaldo_mood_propaga_la_duracion_maxima():
    resultado = agent.nodo_respaldo_mood({"duracion_max": 120})

    assert resultado["messages"][0].tool_calls[0]["args"] == {
        "limite": agent.LIMITE_POOL,
        "duracion_max": 120,
    }
