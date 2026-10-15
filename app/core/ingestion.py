import requests
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import Base, PeliculaDB, SessionLocal, engine

GENEROS_TMDB = {
    18: "Drama",
    10749: "Romántica",
    35: "Comedia",
    27: "Terror",
    878: "Ciencia ficción",
    53: "Thriller",
    16: "Animación",
    28: "Acción",
    12: "Aventura",
}


def obtener_headers() -> dict:
    api_key = (settings.TMDB_API_KEY or "").strip()
    if not api_key:
        raise RuntimeError("Falta TMDB_API_KEY en el entorno (.env).")
    return {
        "accept": "application/json",
        "Authorization": f"Bearer {api_key}",
    }


def obtener_detalles_extra_tmdb(movie_id: int):
    """Devuelve (actores, keywords, director, plataformas) para una película de TMDB."""
    if not movie_id:
        return "", "", "", ""

    base_url = settings.TMDB_BASE_URL.rstrip("/")
    headers = obtener_headers()

    # 1. Reparto principal (primeros 4) y director
    actores = []
    director = ""
    try:
        url_credits = f"{base_url}/movie/{movie_id}/credits"  # Devuelve el equipo técnico
        res_credits = requests.get(url_credits, headers=headers, timeout=15)
        if res_credits.status_code == 200:
            data_credits = res_credits.json()
            actores = [c.get("name", "") for c in data_credits.get("cast", [])[:4]]
            directores = [
                c.get("name", "")
                for c in data_credits.get("crew", [])
                if c.get("job") == "Director"
            ]
            director = ", ".join(filter(None, directores))
    except Exception as e:
        print(f"Error al obtener créditos de {movie_id}: {e}")

    # 2. Palabras clave temáticas (primeras 8)
    keywords = []
    try:
        url_kw = f"{base_url}/movie/{movie_id}/keywords"
        res_kw = requests.get(url_kw, headers=headers, timeout=15)
        if res_kw.status_code == 200:
            data_kw = res_kw.json()
            keywords = [k.get("name", "") for k in data_kw.get("keywords", [])[:8]]
    except Exception as e:
        print(f"Error al obtener keywords de {movie_id}: {e}")

    # 3. Plataformas de streaming disponibles en España (suscripción)
    plataformas = []
    try:
        url_prov = f"{base_url}/movie/{movie_id}/watch/providers"
        res_prov = requests.get(url_prov, headers=headers, timeout=15)
        if res_prov.status_code == 200:
            data_prov = res_prov.json()
            region_es = data_prov.get("results", {}).get("ES", {})
            nombres = [p.get("provider_name", "") for p in region_es.get("flatrate", [])]
            # Elimina duplicados conservando el orden
            plataformas = list(dict.fromkeys(filter(None, nombres)))
    except Exception as e:
        print(f"Error al obtener plataformas de {movie_id}: {e}")

    return (
        ", ".join(filter(None, actores)),
        ", ".join(filter(None, keywords)),
        director,
        ", ".join(plataformas),
    )


def _asegurar_columnas_nuevas() -> None:
    """Añade columnas nuevas a la tabla existente sin borrar los datos."""
    columnas = [("director", "VARCHAR"), ("anio", "INTEGER"), ("plataformas", "VARCHAR")]
    with engine.connect() as conn:
        existentes = {fila[1] for fila in conn.exec_driver_sql("PRAGMA table_info(peliculas)")}
        for nombre, tipo in columnas:
            if nombre not in existentes:
                conn.exec_driver_sql(f"ALTER TABLE peliculas ADD COLUMN {nombre} {tipo}")
                print(f"Columna '{nombre}' añadida a 'peliculas'.")
        conn.commit()


def backfill_detalles() -> None:
    """Rellena director y plataformas en las filas antiguas que aún no los tienen."""
    db: Session = SessionLocal()
    try:
        peliculas = (
            db.query(PeliculaDB)
            .filter((PeliculaDB.director.is_(None)) | (PeliculaDB.plataformas.is_(None)))
            .all()
        )
        print(f"Películas a actualizar: {len(peliculas)}")
        for i, p in enumerate(peliculas, start=1):
            actores, _, director, plataformas = obtener_detalles_extra_tmdb(p.tmdb_id)
            if actores:
                p.actores = actores
            p.director = director
            p.plataformas = plataformas
            if i % 25 == 0:
                db.commit()
                print(f"  {i}/{len(peliculas)} actualizadas...")
        db.commit()
    finally:
        db.close()


def completar_anios(total_paginas: int = 25) -> None:
    """Rellena el año de estreno de las filas que no lo tienen usando /discover/movie."""
    base_url = settings.TMDB_BASE_URL.rstrip("/")
    headers = obtener_headers()

    mapa = {}
    for pagina in range(1, total_paginas + 1):
        try:
            res = requests.get(
                f"{base_url}/discover/movie",
                headers=headers,
                params={"language": "es-ES", "sort_by": "popularity.desc", "page": pagina},
                timeout=30,
            )
            if res.status_code != 200:
                continue
            for p in res.json().get("results", []):
                fecha = p.get("release_date") or ""
                if fecha[:4].isdigit():
                    mapa[p.get("id")] = int(fecha[:4])
        except Exception as e:
            print(f"Error de red en página {pagina}: {e}")

    db: Session = SessionLocal()
    try:
        faltan = db.query(PeliculaDB).filter(PeliculaDB.anio.is_(None)).all()
        actualizados = 0
        for p in faltan:
            if p.tmdb_id in mapa:
                p.anio = mapa[p.tmdb_id]
                actualizados += 1
        db.commit()
        print(f"Años completados: {actualizados}/{len(faltan)}")
    finally:
        db.close()


def poblar_base_datos(total_paginas: int = 25) -> None:
    """Crea el esquema y, si la BD está vacía, descarga el catálogo desde TMDB."""
    print("Verificando esquema de base de datos...")
    Base.metadata.create_all(bind=engine)
    _asegurar_columnas_nuevas()

    db: Session = SessionLocal()
    try:
        conteo_actual = db.query(PeliculaDB).count()
        print(f"Películas en la BD: {conteo_actual}")

        if conteo_actual >= 500:
            print("La base de datos ya cuenta con 500 o más registros. Actualizando detalles...")
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
                "page": pagina,
            }

            try:
                res = requests.get(url, headers=headers, params=params, timeout=30)
            except Exception as e:
                print(f"Error de red en página {pagina}: {e}")
                continue

            if res.status_code != 200:
                print(f"Error en página {pagina} (Status {res.status_code}): {res.text}")
                continue

            peliculas = res.json().get("results", [])

            try:
                for p in peliculas:
                    tmdb_id = p.get("id")
                    if not tmdb_id:
                        continue

                    # Evita duplicados en caso de reejecución
                    if db.query(PeliculaDB).filter(PeliculaDB.tmdb_id == tmdb_id).first():
                        continue

                    nombres_generos = [GENEROS_TMDB.get(gid, "") for gid in p.get("genre_ids", []) if gid in GENEROS_TMDB]
                    actores, keywords, director, plataformas = obtener_detalles_extra_tmdb(tmdb_id)

                    fecha = p.get("release_date") or ""
                    anio = int(fecha[:4]) if fecha[:4].isdigit() else None

                    pelicula_db = PeliculaDB(
                        tmdb_id=tmdb_id,
                        titulo=p.get("title", ""),
                        sinopsis=p.get("overview", ""),
                        generos=", ".join(filter(None, nombres_generos)),
                        actores=actores,
                        keywords=keywords,
                        puntuacion=float(p.get("vote_average", 0.0)),
                        poster_path=p.get("poster_path", ""),
                        director=director,
                        anio=anio,
                        plataformas=plataformas,
                    )
                    db.add(pelicula_db)
                    contador += 1

                db.commit()
            except Exception as e:
                db.rollback()
                print(f"Error guardando página {pagina}: {e}")
                continue

            print(f"Página {pagina}/{total_paginas} completada. Registros totales: {contador}")
    finally:
        db.close()
    print("Ingesta finalizada correctamente.")


if __name__ == "__main__":
    print("Iniciando proceso de ingesta...")
    poblar_base_datos()
    print("Comprobando detalles antiguos (director/plataformas)...")
    backfill_detalles()
    print("Completando años de estreno...")
    completar_anios()
