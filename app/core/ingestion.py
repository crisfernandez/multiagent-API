import sys
from pathlib import Path

# Garantiza la importación de 'app' independientemente de la ruta de ejecución
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

print("⚡ Iniciando proceso de ingesta...")

import requests
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.database import engine, Base, SessionLocal
from app.graph.state import PeliculaDB

GENEROS_TMDB = {
    18: "Drama",
    10749: "Romántica",
    35: "Comedia",
    27: "Terror",
    878: "Ciencia ficción",
    53: "Thriller",
    16: "Animación",
    28: "Acción",
    12: "Aventura"
}

def obtener_headers() -> dict:
    return {
        "accept": "application/json",
        "Authorization": f"Bearer {settings.TMDB_API_KEY.strip()}"
    }

def obtener_detalles_extra_tmdb(movie_id: int):
    if not movie_id:
        return "", ""

    base_url = settings.TMDB_BASE_URL.rstrip("/")
    headers = obtener_headers()
    
    # 1. Reparto principal (primeros 4)
    actores = []
    try:
        url_credits = f"{base_url}/movie/{movie_id}/credits" # Devuelve una lista con el equipo técnico
        res_credits = requests.get(url_credits, headers=headers)
        if res_credits.status_code == 200:
            data_credits = res_credits.json()
            actores = [c.get("name", "") for c in data_credits.get("cast", [])[:4]]
    except Exception as e:
        print(f"Error al obtener créditos de {movie_id}: {e}") # En caso de que no haya reparto, en lugar de fallar, devuelve un texto vacío

    # 2. Palabras clave temáticas (primeras 8)
    keywords = []
    try:
        url_kw = f"{base_url}/movie/{movie_id}/keywords" # Obtiene los términos temáticos específicos
        res_kw = requests.get(url_kw, headers=headers)
        if res_kw.status_code == 200:
            data_kw = res_kw.json()
            keywords = [k.get("name", "") for k in data_kw.get("keywords", [])[:8]]
    except Exception as e:
        print(f"Error al obtener keywords de {movie_id}: {e}")

    return ", ".join(filter(None, actores)), ", ".join(filter(None, keywords))

def poblar_base_datos(total_paginas: int = 25):
    print("Verificando esquema de base de datos...")
    Base.metadata.create_all(bind=engine)
    
    db: Session = SessionLocal()
    conteo_actual = db.query(PeliculaDB).count()
    print(f"Películas en la BD: {conteo_actual}")

    if conteo_actual >= 500:
        print("ℹLa base de datos ya cuenta con 500 o más registros. Finalizando.")
        db.close()
        return

    base_url = settings.TMDB_BASE_URL.rstrip("/")
    headers = obtener_headers()
    contador = conteo_actual

    print("Descargando catálogo desde TMDB...")

    for pagina in range(1, total_paginas + 1):
        url = f"{base_url}/discover/movie"
        params = {
            "language": "es-ES",
            "sort_by": "popularity.desc",
            "page": pagina
        }

        res = requests.get(url, headers=headers, params=params)

        if res.status_code != 200:
            print(f"Error en página {pagina} (Status {res.status_code}): {res.text}")
            continue

        peliculas = res.json().get("results", [])
        
        for p in peliculas:
            tmdb_id = p.get("id")
            if not tmdb_id:
                continue

            # Evita duplicados en caso de reejecución
            if db.query(PeliculaDB).filter(PeliculaDB.tmdb_id == tmdb_id).first(): # Para evitar duplicados
                continue

            nombres_generos = [GENEROS_TMDB.get(gid, "") for gid in p.get("genre_ids", []) if gid in GENEROS_TMDB] # Coniverte los códigos numéricos en nombres legibles (ciencia ficción, terror...)
            actores, keywords = obtener_detalles_extra_tmdb(tmdb_id)

            pelicula_db = PeliculaDB(
                tmdb_id=tmdb_id,
                titulo=p.get("title", ""),
                sinopsis=p.get("overview", ""),
                generos=", ".join(filter(None, nombres_generos)),
                actores=actores,
                keywords=keywords,
                puntuacion=float(p.get("vote_average", 0.0)),
                poster_path=p.get("poster_path", "")
            )
            db.add(pelicula_db)
            contador += 1

        db.commit()
        print(f"Página {pagina}/{total_paginas} completada. Registros totales: {contador}")

    db.close()
    print("Ingesta finalizada correctamente.")

if __name__ == "__main__":
    poblar_base_datos()