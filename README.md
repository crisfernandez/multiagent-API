# REEL80 · Videoclub Neón

Recomendador de cine con **sistema multiagente** construido con [LangGraph](https://langchain-ai.github.io/langgraph/), FastAPI y un LLM local (Ollama).


---

## Lo importante no es la app: es el sistema multiagente

Este proyecto existe para practicar **cómo se construye un grafo de agentes que funcione de verdad**, no para ser un recomendador rápido. Dentro del grafo conviven agentes con responsabilidades distintos que se comunican a través de un estado compartido:

| Agente / nodo | Trabajo que hace |
|---|---|
| **① Router** | Clasifica la intención (actor / género / mood) con LLM de salida estructurada y extrae la entidad. |
| **② Preparar búsqueda** | Traduce la intención a argumentos reales de la herramienta. |
| **③ Analizar mood** | "Psicólogo": convierte emociones en géneros (español, para la BD) y keywords TMDB (inglés). |
| **④ Tools (ToolNode)** | Único punto donde se ejecuta SQL real sobre el catálogo. |
| **⑤ Extraer resultados** | JSON de la herramienta → estado estructurado que consume la API. |
| **⑥ Redactor** | Presenta las películas con palabras propias. |
| **Respaldo / Reintento** | Recuperación de errores: si la búsqueda sale vacía, reintenta con una heurística **sin LLM** o degrada al catálogo mejor valorado. |

La parte interesante está en lo que ocurre cuando algo falla: rutas condicionales, un reintento que no cuesta una llamada al LLM, un respaldo degradado para no dejar la pantalla vacía y memoria de conversación por sesión (`MemorySaver`).

---

## Diagrama del grafo

```
                               ┌──────────┐
                               │  START   │
                               └────┬─────┘
                                    ▼
                  ┌───────────────────────────────────┐
                  │  ①  ROUTER   (agente · LLM)       │
                  │  clasifica: actor | género | mood │
                  └───┬──────────────┬────────────┬───┘
       actor/género   │              │ mood       │ sin entidad
                      ▼              ▼            ▼
   ┌───────────────────────────┐ ┌────────────┐ ┌──────────────────┐
   │ ②  PREPARAR_BÚSQUEDA      │◄│ ③  ANALIZAR│ │ PEDIR_ACLARACIÓN │─► END
   │ arma los argumentos       │ │    MOOD    │ └──────────────────┘
   └────────────┬──────────────┘ │ (psicólogo)│
                │                └────────────┘
                ▼
   ┌────────────────────────────────────────────┐
   │ ④  TOOLS · ToolNode → buscar_peliculas     │
   │     consulta real a SQLite (613 películas) │
   └───────────────────┬────────────────────────┘
                       ▼
   ┌────────────────────────────────────────────┐
   │ ⑤  EXTRAER_RESULTADOS                      │
   │     JSON → estado["peliculas"] (pool de 60)│
   └───────────────────┬────────────────────────┘
                       ▼
                ¿hay resultados?
                │                │
          SÍ    ▼          NO    ▼
   ┌───────────────────┐  ┌──────────────────────────────┐
   │ ⑥  REDACTAR       │  │ ¿mood?       → RESPALDO_MOOD│
   │     presenta las  │  │ ¿heurística? → REINTENTAR   │
   │     películas     │  │ ¿nada?       → REDACTAR     │
   └─────────┬─────────┘  └──────────────┬───────────────┘
             ▼                           │ vuelven a ④
            END ◄────────────────────────┘
```

---

## Estructura del proyecto

```
API_Grafos/
├── app/
│   ├── api.py              # FastAPI: invoca el grafo y pagina su salida
│   ├── core/
│   │   ├── config.py       # Settings (lee el .env)
│   │   ├── database.py     # Modelo PeliculaDB + SQLite (cine.db)
│   │   ├── ingestion.py    # Poblado del catálogo desde TMDB
│   │   ├── tmdb.py         # Ficha en vivo de TMDB
│   │   └── cache.py        # Caché TTL para no repetir llamadas al LLM
│   ├── graph/
│   │   ├── agent.py        # ← el grafo multiagente (el motor)
│   │   ├── state.py        # Estado compartido + modelos estructurados del LLM
│   │   └── tools.py        # Tool del LLM + consultas a la BD
│   └── static/             # Frontend (HTML/CSS/JS vanilla, sin build)
├── test_graph.py           # Prueba manual del grafo
├── requirements.txt
└── .env.example
```

---

## Quickstart

Requisitos: **Python 3.10+**, **[Ollama](https://ollama.com)** con el modelo `qwen2.5:3b` y una **clave de API de TMDB** (gratuita en <https://www.themoviedb.org/settings/api>).

```bash
# 1. Dependencias
pip install -r requirements.txt

# 2. Configuración
cp .env.example .env        # Windows: copy .env.example .env
#    y pega tu TMDB_API_KEY dentro de .env

# 3. Modelo del LLM local
ollama pull qwen2.5:3b
ollama serve                # si no lo tienes ya corriendo

# 4. Catálogo (613 películas: ~10-15 min porque consulta TMDB película a película)
python -m app.core.ingestion

# 5. Arrancar
python -m uvicorn app.api:app --port 8010
# abre http://localhost:8010
```

Prueba manual del grafo sin API (imprime la intención detectada y la respuesta del redactor):

```bash
python test_graph.py
```

---

## Sobre la latencia: lee esto

Las peticiones **tardan** (~2-3 min la primera vez). No es un descuido: el grafo ejecuta varias llamadas a un **LLM local de 3B parámetros** (router, psicólogo, redactor) y `qwen2.5:3b` corriendo en CPU no es rápido. Repetir la misma búsqueda o pulsar *OTRAS 10* es inmediato porque hay una caché TTL que evita repetir el LLM.

**La importancia del proyecto no es la velocidad de la app, sino el sistema multiagente y que funcione bien**: que el enrutado sea fiable, que las herramientas devuelvan datos reales, que haya memoria por sesión, que un error de clasificación se detecte y se corrija dentro del propio grafo, y que nunca se quede la pantalla en blanco. La latencia se reduciría con un modelo remoto o más grande, pero eso queda fuera del alcance de este ejercicio.

---

## Endpoints

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/health` | Comprobación de que la API vive. |
| `POST` | `/recomendar` | Invoca el grafo (o su caché) y pagina el pool a 10 películas. |
| `GET` | `/pelicula/{tmdb_id}` | Ficha en vivo de TMDB (detalles + créditos + proveedores ES). |
| `GET` | `/` | Frontend. |
| `GET` | `/static/*` | CSS y JS del frontend. |


## Licencia / datos

Datos de películas de [TMDB](https://www.themoviedb.org). Este proyecto no está respaldado ni certificado por TMDB.
