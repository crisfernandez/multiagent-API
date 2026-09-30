import requests
from app.core.config import settings

token = settings.TMDB_API_KEY.strip()
base_url = settings.TMDB_BASE_URL.rstrip("/")
url = f"{base_url}/discover/movie"

headers = {
    "accept": "application/json",
    "Authorization": f"Bearer {token}"
}

params = {
    "language": "es-ES",
    "page": 1
}

print("--- DIAGNÓSTICO ---")
print(f"URL: {url}")
print(f"Longitud del token: {len(token)}")
print(f"Primeros 10 caracteres del token: {token[:10]}...")
print("Enviando petición...")

res = requests.get(url, headers=headers, params=params)

print(f"Código HTTP: {res.status_code}")
print(f"Respuesta TMDB: {res.text}")