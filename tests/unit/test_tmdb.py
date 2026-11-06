"""Tests de la ficha en vivo de TMDB, con `requests.get` simulado."""

import pytest

from app.core import tmdb


class Respuesta:
    def __init__(self, status_code=200, datos=None):
        self.status_code = status_code
        self._datos = datos or {}

    def json(self):
        return self._datos


@pytest.fixture(autouse=True)
def clave_valida(monkeypatch):
    monkeypatch.setattr(tmdb.settings, "TMDB_API_KEY", "clave-test")


def _instalar_http(monkeypatch, respuestas):
    llamadas = []

    def get(url, **kwargs):
        llamadas.append({"url": url, **kwargs})
        for sufijo, respuesta in respuestas.items():
            if url.endswith(sufijo):
                return respuesta
        raise AssertionError(f"URL inesperada: {url}")

    monkeypatch.setattr(tmdb.requests, "get", get)
    return llamadas


def _detalle(**cambios):
    base = {
        "title": "Origen",
        "release_date": "2010-07-16",
        "overview": "Ladrones de sueños.",
        "vote_average": 8.4,
        "runtime": 148,
        "tagline": "Tu mente es la escena del crimen.",
        "poster_path": "/origen.jpg",
        "genres": [{"name": "Acción"}, {"name": "Ciencia ficción"}],
    }
    base.update(cambios)
    return Respuesta(200, base)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def test_headers_exige_clave(monkeypatch):
    monkeypatch.setattr(tmdb.settings, "TMDB_API_KEY", "  ")

    with pytest.raises(RuntimeError, match="TMDB_API_KEY"):
        tmdb._headers()


def test_headers_construye_bearer_y_limpia_espacios(monkeypatch):
    monkeypatch.setattr(tmdb.settings, "TMDB_API_KEY", "  abc123  ")

    assert tmdb._headers() == {
        "accept": "application/json",
        "Authorization": "Bearer abc123",
    }


def test_plataformas_limpia_ruido_y_duplicados():
    region = {
        "flatrate": [
            {"provider_name": "Netflix"},
            {"provider_name": "Netflix with Ads"},
            {"provider_name": "Netflix Channel"},
            {"provider_name": ""},
            {"provider_name": "Prime Video"},
            {"provider_name": "Netflix"},
        ]
    }

    assert tmdb._plataformas(region) == ["Netflix", "Prime Video"]


def test_plataformas_sin_flatrate():
    assert tmdb._plataformas({}) == []


# ---------------------------------------------------------------------------
# obtener_ficha
# ---------------------------------------------------------------------------


def test_obtener_ficha_unifica_detalle_creditos_y_plataformas(monkeypatch):
    llamadas = _instalar_http(
        monkeypatch,
        {
            "/credits": Respuesta(
                200,
                {
                    "cast": [{"name": f"Actor {i}"} for i in range(10)],
                    "crew": [
                        {"name": "Christopher Nolan", "job": "Director"},
                        {"name": "Emma Thomas", "job": "Producer"},
                        {"name": "Otro Director", "job": "Director"},
                    ],
                },
            ),
            "/watch/providers": Respuesta(
                200,
                {
                    "results": {
                        "ES": {
                            "flatrate": [
                                {"provider_name": "Netflix"},
                                {"provider_name": "Netflix with Ads"},
                                {"provider_name": "Prime Video"},
                            ]
                        }
                    }
                },
            ),
            "/movie/27205": _detalle(),
        },
    )

    ficha = tmdb.obtener_ficha(27205)

    assert ficha == {
        "tmdb_id": 27205,
        "titulo": "Origen",
        "anio": 2010,
        "sinopsis": "Ladrones de sueños.",
        "nota": 8.4,
        "duracion": 148,
        "tagline": "Tu mente es la escena del crimen.",
        "poster": "https://image.tmdb.org/t/p/w500/origen.jpg",
        "generos": ["Acción", "Ciencia ficción"],
        "director": "Christopher Nolan, Otro Director",
        "reparto": [f"Actor {i}" for i in range(8)],
        "plataformas": ["Netflix", "Prime Video"],
    }
    assert llamadas[0]["params"] == {"language": "es-ES"}
    assert llamadas[0]["timeout"] == 15
    assert llamadas[0]["headers"]["Authorization"] == "Bearer clave-test"


def test_obtener_ficha_inexistente_lanza_value_error(monkeypatch):
    llamadas = _instalar_http(monkeypatch, {"/movie/999": Respuesta(404)})

    with pytest.raises(ValueError, match="TMDB respondió 404"):
        tmdb.obtener_ficha(999)

    assert len(llamadas) == 1


def test_obtener_ficha_tolera_fallo_de_creditos_y_plataformas(monkeypatch):
    _instalar_http(
        monkeypatch,
        {
            "/credits": Respuesta(500),
            "/watch/providers": Respuesta(500),
            "/movie/1": _detalle(title="Sin extras"),
        },
    )

    ficha = tmdb.obtener_ficha(1)

    assert ficha["reparto"] == []
    assert ficha["director"] == ""
    assert ficha["plataformas"] == []


@pytest.mark.parametrize(
    ("fecha", "anio"),
    [("2010-07-16", 2010), ("2010", 2010), ("", None), ("sin fecha", None)],
)
def test_obtener_ficha_parsea_el_anio(monkeypatch, fecha, anio):
    _instalar_http(
        monkeypatch,
        {
            "/credits": Respuesta(200, {}),
            "/watch/providers": Respuesta(200, {}),
            "/movie/1": _detalle(release_date=fecha),
        },
    )

    assert tmdb.obtener_ficha(1)["anio"] == anio


def test_obtener_duracion_tmdb_devuelve_runtime(monkeypatch):
    llamadas = _instalar_http(
        monkeypatch,
        {"/movie/27205": Respuesta(200, {"runtime": 148})},
    )

    assert tmdb.obtener_duracion_tmdb(27205) == 148
    assert llamadas[0]["url"].endswith("/movie/27205")
    assert llamadas[0]["params"] == {"language": "es-ES"}


def test_obtener_duracion_tmdb_sin_runtime_devuelve_none(monkeypatch):
    _instalar_http(
        monkeypatch,
        {"/movie/1": Respuesta(200, {"runtime": None})},
    )

    assert tmdb.obtener_duracion_tmdb(1) is None


def test_obtener_duracion_tmdb_tolera_errores(monkeypatch):
    _instalar_http(monkeypatch, {"/movie/2": Respuesta(404)})

    assert tmdb.obtener_duracion_tmdb(2) is None


def test_obtener_duracion_tmdb_tolera_fallo_de_red(monkeypatch):
    def get(url, **kwargs):
        raise tmdb.requests.RequestException("sin red")

    monkeypatch.setattr(tmdb.requests, "get", get)

    assert tmdb.obtener_duracion_tmdb(3) is None


def test_obtener_ficha_sin_poster_devuelve_none(monkeypatch):
    _instalar_http(
        monkeypatch,
        {
            "/credits": Respuesta(200, {}),
            "/watch/providers": Respuesta(200, {}),
            "/movie/1": _detalle(poster_path=None),
        },
    )

    assert tmdb.obtener_ficha(1)["poster"] is None
