# AGENTS.md

Proyecto con agentes: Sistema multiagente usando el framework de langgraph. Es un proyecto de aprendizaje así que no uses codigo muy complejo.

## Entrypoints (no obvios)
- App real: `app/api.py:app` (`app/main.py` está vacío, no usar). Run: `py -m uvicorn app.api:app --port 8010` (el **8000 lo usa otra app** del usuario).
- Grafo real: `app/graph/agent.py:grafo` (`StateGraph(EstadoRecomendador)`). **El grafo es el motor**: la API solo lo invoca y pagina su salida.
- Ingesta TMDB: `py -m app.core.ingestion` (puebla `cine.db` vía `discover/movie` + `credits` + `keywords` + `watch/providers`, y hace backfill de director/año/plataformas).
- Prueba manual: `test_graph.py` (requiere Ollama con `qwen2.5:3b`). Usa `config={"configurable": {"thread_id": ...}}` (obligatorio por `MemorySaver`).

## Estructura
- `app/core/config.py`: `Settings` (`TMDB_API_KEY`, `TMDB_BASE_URL`, `DATABASE_URL=sqlite:///./cine.db`). Lee `.env`.
- `app/core/database.py`: modelo `PeliculaDB` (columnas: titulo, sinopsis, generos, actores, keywords, puntuacion, poster_path, **director, anio, plataformas**), `engine` SQLite, `SessionLocal`.
- `app/core/cache.py`: `CacheTTL` (TTL + límite + lock entre hilos). Usada por la API.
- `app/core/tmdb.py`: `obtener_ficha(tmdb_id)` → ficha en vivo (details + credits + providers ES).
- `app/graph/state.py`: `EstadoRecomendador` incluye `peliculas: List[dict]` (pool que alimenta la API), `ya_reintentado`, `respaldo_mood`, `generos_mood`. `tipo_intencion` admite también `"titulo"`. `AnalisisEmocional` devuelve `mood_detectado` + `generos` (lista cerrada en español) + `keywords` (en inglés, p/ catálogo TMDB).
- `app/graph/tools.py`:
  - `buscar_peliculas` (tool del LLM) → envuelve `consultar_peliculas` y devuelve **JSON** `{"sin_resultados": bool, "peliculas": [...]}`.
  - `consultar_peliculas(actor, genero, generos, titulo, keywords, limite, excluir_ids)` → objetos `PeliculaDB`. El mood usa `generos` + `keywords` combinados con **OR** (a más criterios, más resultados). Match por tokens, título y respaldo sin acentos. `_mapear_generos` traduce los géneros en inglés que a veces devuelve el LLM a los valores en español de la BD.
  - `detectar_termino_catalogo(mensaje)` → heurística sobre el catálogo (género/título/actor) cuando el router del LLM falla.
- `app/graph/agent.py`: flujo `START -> router -cond-> analizar_mood|preparar_busqueda|pedir_aclaracion`; `analizar_mood` extrae `generos_mood` + `keywords` y se los pasa a `preparar_busqueda`; `preparar_busqueda -> tools(ToolNode) -> extraer_resultados -cond-> redactar|reintentar_catalogo|respaldo_mood`; `reintentar/respaldo -> tools`. LLM: `ChatOllama(model="qwen2.5:3b", temperature=0)` + `with_structured_output`.
- `app/api.py`: API delgada. Endpoints: `GET /health`, `POST /recomendar` (invoca el grafo o su caché y pagina el pool a 10), `GET /pelicula/{tmdb_id}` (ficha TMDB en vivo), `GET /` y `/static/*`.
- Frontend en `app/static/` (index.html, styles.css, app.js). JS vanilla, sin build.

## Gotchas verificados
- La API **no consulta la BD directamente**: la lista que se pinta sale del `estado["peliculas"]` que produce el ToolNode del grafo. No reintroducir una consulta paralela.
- `poster_url` ya no existe: usar `TMDB_IMAGE_BASE_URL + poster_path` (ver `pelicula_a_dict`).
- El clasificador `qwen2.5:3b` a veces falla (p.ej. "películas con Tom Hanks" → género); lo mitiga `nodo_reintentar_catalogo` + `detectar_termino_catalogo` **dentro del grafo**.
- Las `keywords` de la BD están **en inglés** (TMDB no las traduce); por eso el psicólogo genera keywords en inglés y el mood busca principalmente por `generos` (que sí está en español, con cientos de películas por género).
- `qwen2.5:3b` a veces devuelve los géneros del mood en inglés pese a pedirle la lista española; lo mitiga `_mapear_generos` en `tools.py`.
- `random.py` de la raíz fue **borrado** (rompía `asyncio`/FastAPI por shadowing).
- Ollama debe estar corriendo antes de invocar el grafo; la **1ª petición** de una búsqueda nueva tarda ~2-3 min (varias llamadas al LLM). Repetirla es rápido por `_cache_grafo`.
- `detectar_termino_catalogo` exige al menos una letra/número en la coincidencia (evita que títulos no latinos, que normalizan a un espacio, casen con cualquier mensaje). Puede hacer match de títulos muy cortos (p.ej. "xyz" → película "X"); es conocido y no produce bucles.
- No hay lint/typecheck/CI/tests configurados; `pyproject.toml`, `Dockerfile`, `docker-compose.yml`, `app/main.py`, `app/api/routes.py`, `app/core/security.py` están vacíos (0 bytes).

## Restricciones:
- Siempre pregunta antes de llevar a cabo algún cambio en cualquiera de los archivos, ya sea eliminar o añadir algo.
- Después de haberse autorizado, explica qué codigo has añadido, para qué sirve y por qué ayuda a alcanzar el objetivo buscado.
