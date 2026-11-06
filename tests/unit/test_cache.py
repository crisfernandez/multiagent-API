"""Tests de `CacheTTL`: caducidad, límite de tamaño y sobrescritura."""

from types import SimpleNamespace

import pytest

from app.core import cache


@pytest.fixture
def reloj(monkeypatch):
    estado = SimpleNamespace(ahora=1000.0)
    monkeypatch.setattr(cache, "time", SimpleNamespace(time=lambda: estado.ahora))
    return estado


def test_obtener_clave_inexistente_devuelve_none(reloj):
    almacen = cache.CacheTTL()

    assert almacen.obtener("nada") is None


def test_guardar_y_obtener(reloj):
    almacen = cache.CacheTTL()

    almacen.guardar("clave", {"valor": 1})

    assert almacen.obtener("clave") == {"valor": 1}


def test_guardar_sobrescribe_el_valor_anterior(reloj):
    almacen = cache.CacheTTL()

    almacen.guardar("clave", "viejo")
    almacen.guardar("clave", "nuevo")

    assert almacen.obtener("clave") == "nuevo"


def test_la_entrada_sigue_viva_justo_en_el_ttl(reloj):
    almacen = cache.CacheTTL(ttl_segundos=10)
    almacen.guardar("clave", "valor")

    reloj.ahora += 10

    assert almacen.obtener("clave") == "valor"


def test_la_entrada_caduca_al_superar_el_ttl(reloj):
    almacen = cache.CacheTTL(ttl_segundos=10)
    almacen.guardar("clave", "valor")

    reloj.ahora += 11

    assert almacen.obtener("clave") is None
    assert "clave" not in almacen._datos


def test_desaloja_la_entrada_mas_antigua_al_llenarse(reloj):
    almacen = cache.CacheTTL(max_items=2)

    almacen.guardar("a", 1)
    reloj.ahora += 1
    almacen.guardar("b", 2)
    reloj.ahora += 1
    almacen.guardar("c", 3)

    assert almacen.obtener("a") is None
    assert almacen.obtener("b") == 2
    assert almacen.obtener("c") == 3


def test_con_max_items_uno_solo_sobrevive_el_ultimo(reloj):
    almacen = cache.CacheTTL(max_items=1)

    almacen.guardar("a", 1)
    almacen.guardar("b", 2)

    assert almacen.obtener("a") is None
    assert almacen.obtener("b") == 2


def test_una_clave_caducada_se_desaloja_antes_que_una_viva(reloj):
    almacen = cache.CacheTTL(ttl_segundos=100, max_items=2)
    almacen.guardar("a", 1)
    reloj.ahora += 50
    almacen.guardar("b", 2)

    reloj.ahora += 60
    assert almacen.obtener("a") is None

    almacen.guardar("c", 3)

    assert almacen.obtener("b") == 2
    assert almacen.obtener("c") == 3
