# AGENTS.md

Proyecto con agentes: Sistema multiagente usando el framework de langgraph. Es un proyecto de aprendizaje así que no uses codigo muy complejo.

## Entrypoints (no obvios)
- App real: `app/api.py:app` (`app/main.py` está vacío, no usar). Run: `uvicorn app.api:app --reload`.
- Grafo real: `app/graph/agent.py:grafo` (`StateGraph(EstadoRecomendador)`). `app/api.py` importa `graph` con `MessagesState` — nombre y estado desactualizados, no arranca tal cual.
- Ingesta TMDB: `python -m app.core.ingestion` (puebla `cine.db` vía `discover/movie` + `credits` + `keywords`).
- Prueba manual: `python test_graph.py` (requiere Ollama con `qwen2.5:3b`). Usa `from app.graph.agent import grafo` + `config={"configurable": {"thread_id": ...}}` (obligatorio por `MemorySaver`).

## Estructura
- `app/core/config.py`: `Settings` (`TMDB_API_KEY`, `TMDB_BASE_URL`, `DATABASE_URL=sqlite:///./cine.db`). Lee `.env` con `load_dotenv`. `.env.example` está vacío, no fiarse.
- `app/core/database.py`: `engine` SQLite con `check_same_thread=False`, `SessionLocal`, `Base`.
- `app/graph/state.py`: mezcla modelo `PeliculaDB` + `EstadoRecomendador(TypedDict)` + esquemas `ClasificacionIntencion`/`AnalisisEmocional`. `ingestion.py` y `tools.py` importan el modelo desde aquí (dependencia `core -> graph` invertida).
- `app/graph/agent.py`: flujo `START -> router -condicional-> analizar_mood|consultar_bd -> consultar_bd -> redactar -> END`. LLM: `ChatOllama(model="qwen2.5:3b", temperature=0)` + `with_structured_output`.
- `app/graph/tools.py`: `buscar_peliculas(actor,genero,keywords)` con `ilike` + `or_`, ordena por `puntuacion`. Devuelve `str`, no objetos.
- `app/api/` (directorio) está casi vacío (`routes.py` vacío, `schemas.py` duplica `ChatRequest/ResumeRequest` sin usarse). No confundir con `app/api.py` (fichero).

## Gotchas verificados
- `tools.py` usa `p.poster_url` pero el modelo solo tiene `poster_path` → `AttributeError` siempre que hay resultados. Usar `TMDB_IMAGE_BASE_URL + poster_path`.
- `requirements.txt` incompleto: falta `sqlalchemy` y `python-dotenv` aunque el código los importa. `pip install` limpio + `python -c "import sqlalchemy"` falla.
- `pyproject.toml`, `Dockerfile`, `docker-compose.yml`, `app/main.py`, `app/api/routes.py`, `app/core/security.py` están vacíos (0 bytes). No hay lint/typecheck/CI/tests configurados.
- `ingestion.py` hace `sys.path.append(...)` y `print()` a nivel de import; no importar este módulo desde el grafo/API, solo ejecutarlo como script.
- Ollama debe estar corriendo con `qwen2.5:3b` antes de `test_graph.py` o cualquier nodo LLM; si no, el fallo es de conexión, no del grafo.
- `cine.db` está en disco pero ignorado por `.gitignore`; no asumir que existe en clon limpio — correr ingesta primero.

## Restricciones:
- Siempre pregunta antes de llevar a cabo algún cambio en cualquiera de los archivos, ya sea eliminar o añadir algo.
- Después de haberse autorizado, explica qué codigo has añadido, para qué sirve y por qué ayuda a alcanzar el objetivo buscado.
