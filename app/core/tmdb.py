import requests

from app.core.config import settings

TMDB_IMAGE_BASE_URL = "https://image.tmdb.org/t/p/w500"


def _headers() -> dict:
    api_key = (settings.TMDB_API_KEY or "").strip()
    if not api_key:
        raise RuntimeError("Falta TMDB_API_KEY en el entorno (.env).")
    return {
        "accept": "application/json",
        "Authorization": f"Bearer {api_key}",
    }


def _plataformas(region: dict) -> list:
    """Plataformas de suscripción limpias (sin duplicados ni variantes ruidosas)."""
    nombres = [p.get("provider_name", "") for p in region.get("flatrate", [])]
    limpias = []
    for nombre in nombres:
        if not nombre or "with Ads" in nombre or nombre.endswith("Channel"):
            continue
        if nombre not in limpias:
            limpias.append(nombre)
    return limpias


def obtener_ficha(tmdb_id: int) -> dict:
    """Consulta TMDB en vivo y devuelve una ficha unificada en español.

    Lanza RuntimeError/ValueError si la película no existe o TMDB no responde.
    """
    base_url = settings.TMDB_BASE_URL.rstrip("/")
    headers = _headers()

    res = requests.get(
        f"{base_url}/movie/{tmdb_id}",
        headers=headers,
        params={"language": "es-ES"},
        timeout=15,
    )
    if res.status_code != 200:
        raise ValueError(f"TMDB respondió {res.status_code} para la película {tmdb_id}.")

    detalle = res.json()

    reparto = []
    director = ""
    res_credits = requests.get(f"{base_url}/movie/{tmdb_id}/credits", headers=headers, timeout=15)
    if res_credits.status_code == 200:
        creditos = res_credits.json()
        reparto = [c.get("name", "") for c in creditos.get("cast", [])[:8]]
        directores = [c.get("name", "") for c in creditos.get("crew", []) if c.get("job") == "Director"]
        director = ", ".join(filter(None, directores))

    plataformas = []
    res_prov = requests.get(f"{base_url}/movie/{tmdb_id}/watch/providers", headers=headers, timeout=15)
    if res_prov.status_code == 200:
        region_es = res_prov.json().get("results", {}).get("ES", {})
        plataformas = _plataformas(region_es)

    fecha = detalle.get("release_date") or ""
    anio = int(fecha[:4]) if fecha[:4].isdigit() else None
    poster_path = detalle.get("poster_path")

    return {
        "tmdb_id": tmdb_id,
        "titulo": detalle.get("title"),
        "anio": anio,
        "sinopsis": detalle.get("overview"),
        "nota": detalle.get("vote_average"),
        "duracion": detalle.get("runtime"),
        "tagline": detalle.get("tagline"),
        "poster": f"{TMDB_IMAGE_BASE_URL}{poster_path}" if poster_path else None,
        "generos": [g.get("name", "") for g in detalle.get("genres", [])],
        "director": director,
        "reparto": reparto,
        "plataformas": plataformas,
    }
