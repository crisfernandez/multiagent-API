"""Tests de los nodos de mood: análisis, redacción y aclaración."""

from langchain_core.messages import AIMessage

from app.graph import agent
from app.graph.state import AnalisisEmocional


def test_analizar_mood_limpia_y_limita_las_listas(fakes):
    fakes.psicologo.respuestas = [
        AnalisisEmocional(
            mood_detectado="nostálgico",
            generos=[" Drama ", "", "Romántica", "Comedia", "Acción"],
            keywords=[" friendship ", "", "a", "b", "c", "d"],
        )
    ]

    resultado = agent.nodo_analizar_mood({"mensaje_usuario": "Me siento nostálgico"})

    assert resultado == {
        "mood_detectado": "nostálgico",
        "generos_mood": ["Drama", "Romántica", "Comedia"],
        "keywords": ["friendship", "a", "b", "c", "d"],
    }
    assert "Me siento nostálgico" in fakes.psicologo.llamadas[0]


def test_redactar_incluye_mood_y_peliculas_en_el_prompt(fakes):
    fakes.redactor.respuestas = [AIMessage(content="Aquí tienes tu recomendación")]

    resultado = agent.nodo_redactar(
        {
            "peliculas": [{"titulo": "Forrest Gump", "nota": 8.8}],
            "mood_detectado": "nostálgico",
            "tipo_intencion": "mood",
        }
    )

    assert resultado == {"respuesta_final": "Aquí tienes tu recomendación"}
    prompt = fakes.redactor.llamadas[0]
    assert "nostálgico" in prompt
    assert "Forrest Gump" in prompt
    assert "no hay resultados" not in prompt


def test_redactar_sin_mood_usa_el_tipo_de_intencion(fakes):
    fakes.redactor.respuestas = [AIMessage(content="ok")]

    agent.nodo_redactar(
        {"peliculas": [{"titulo": "Origen"}], "tipo_intencion": "actor"}
    )

    assert "El usuario buscó por: actor." in fakes.redactor.llamadas[0]


def test_redactar_avisa_cuando_no_hay_resultados(fakes):
    fakes.redactor.respuestas = [AIMessage(content="No encontré nada")]

    resultado = agent.nodo_redactar({"peliculas": [], "tipo_intencion": "genero"})

    assert resultado["respuesta_final"] == "No encontré nada"
    prompt = fakes.redactor.llamadas[0]
    assert "No se encontraron películas con esos criterios." in prompt
    assert "no hay resultados" in prompt


def test_pedir_aclaracion_ofrece_las_tres_opciones():
    resultado = agent.nodo_pedir_aclaracion({})

    respuesta = resultado["respuesta_final"]
    assert "actor" in respuesta
    assert "género" in respuesta
    assert "estado de ánimo" in respuesta
