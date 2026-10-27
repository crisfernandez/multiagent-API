# REEL80

Recomendador de cine con **sistema multiagente** construido con [LangGraph](https://langchain-ai.github.io/langgraph/), FastAPI y un LLM local (Ollama).


---

## Lo importante no es la app: es el sistema multiagente

Este proyecto existe para practicar **cómo se construye un grafo de agentes que funcione de verdad**, no para ser un recomendador rápido. Dentro del grafo conviven agentes con responsabilidades distintas que se comunican a través de un estado compartido:

| Agente / nodo | Trabajo que hace |
|---|---|
| **① Router** | Clasifica la intención (actor / género / mood) con LLM de salida estructurada y extrae la entidad. Además resetea el estado de búsquedas anteriores. |
| **② Analizar mood** | "Psicólogo": convierte emociones en géneros (español, para la BD) y keywords TMDB (inglés). |
| **③ Agente (ReAct)** | **El único que decide si usar la herramienta.** Recibe el contexto ya extraído, razona si necesita el catálogo y emite la llamada con los argumentos que considere oportunos — o no la emite. |
| **④ Tools (ToolNode)** | Único punto donde se ejecuta SQL real sobre el catálogo. |
| **⑤ Extraer resultados** | JSON de la herramienta → estado estructurado que consume la API. |
| **⑥ Redactor** | Presenta las películas con palabras propias (es el único texto que ve el usuario). |
| **⑦ Respaldo mood / ⑧ Reintento** | Recuperación de errores **sin LLM**: si todo lo anterior sale vacío, reintenta con una heurística sobre el catálogo o degrada al catálogo mejor valorado. |

### Cómo se comunican entre sí

Los nodos **nunca hablan directamente** entre sí: la única vía de comunicación es el **estado compartido** (`EstadoRecomendador`). Cada nodo recibe el estado completo, hace su trabajo y devuelve un diccionario parcial que LangGraph fusiona; las aristas condicionales deciden quién va después.

La comunicación **agente ↔ herramienta** sigue el protocolo de tool-calling de LangChain sobre la lista `messages`:

1. El agente devuelve un `AIMessage` con `tool_calls=[{name, args, id}]` (o sin ellos = "no necesito buscar").
2. El `ToolNode` ejecuta la SQL y añade un `ToolMessage` con el JSON `{"sin_resultados": bool, "peliculas": [...]}`.
3. Ese resultado **vuelve al contexto del agente**, que puede ver "0 resultados" y reformular la búsqueda, o dar por buena la búsqueda y parar.

### El estado compartido

| Campo | Quién lo escribe | Para qué sirve |
|---|---|---|
| `mensaje_usuario` | API (entrada) | Texto crudo del usuario. |
| `messages` | router → agente → ToolNode | Historial conversacional que lee el LLM (reductor `add_messages`). |
| `tipo_intencion` | router | `actor` \| `genero` \| `mood` \| `titulo` — gobierna las bifurcaciones. |
| `termino_busqueda` | router / heurística | Entidad extraída ("Tom Hanks", "Comedia"). |
| `mood_detectado` | psicólogo | Resumen emocional ("cansado, triste"). |
| `generos_mood` | psicólogo | 1-3 géneros **en español** (columna `generos` de la BD). |
| `keywords` | psicólogo | 2-5 keywords **en inglés** (columna `keywords`; TMDB no traduce). |
| `peliculas` | extraer resultados | El **pool** (hasta 60) que pagina la API. Siempre sale del ToolNode. |
| `ya_reintentado` | nodos de fallback | Cortafías de bucle: un solo reintento por búsqueda. |
| `respaldo_mood` | respaldo mood | Flag que el frontend muestra como aviso. |
| `respuesta_final` | redactor | El texto Markdown final. |

---

## Diagrama del grafo

```
                                ┌──────────┐
                                │  START   │
                                └────┬─────┘
                                     ▼
                   ┌────────────────────────────────────┐
                   │ ① ROUTER · LLM estructurado        │
                   │ clasifica: actor │ género │ mood   │
                   └───┬───────────────┬───────────┬────┘
       actor / género  │               │ mood      │ sin entidad
                       │               ▼           ▼
                       │        ┌─────────────┐ ┌──────────────────┐
                       │        │ ② ANALIZAR  │ │ PEDIR_ACLARACIÓN │─► END
                       │        │    MOOD     │ └──────────────────┘
                       │        │ (psicólogo) │
                       │        └──────┬──────┘
                       ▼               ▼
        ┌──────────────────────────────────────────────┐
        │ ③ AGENTE · LLM con bind_tools                │
        │    razona: ¿consulta el catálogo o respondo? │
        └───┬──────────────────────────────────────┬───┘
            │ CON tool_calls                       │ SIN tool_calls
            ▼                                      ▼
  ┌──────────────────────────┐         ┌──────────────────────────────────────┐
  │ ④ TOOLS · ToolNode       │         │ ¿hay resultados o ya_reintentado?    │
  │    SQL real → SQLite     │         │   SÍ ─────► ⑥ REDACTAR ─────► END    │
  └────────────┬─────────────┘         │   NO ──► FALLBACKS ──┐               │
               ▼                       └──────────────────────┼───────────────┘
  ┌──────────────────────────┐                                │
  │ ⑤ EXTRAER_RESULTADOS     │                                │
  │    JSON → estado         │                                │
  └────────────┬─────────────┘                                │
               │                                              │
               └──────────────► ③ AGENTE ◄────────────────────┘

   FALLBACKS (deterministas, sin LLM, acotados por `ya_reintentado`,
   y vuelven a ④ TOOLS para que el agente decida otra vez):
     ⑦ RESPALDO_MOOD · es mood → catálogo sin filtros (lo mejor valorado)
     ⑧ REINTENTAR    · heurística `detectar_termino_catalogo` o término del router
     si nada funciona → ⑥ REDACTAR sin resultados (lo dice con honestidad)
```

---

## El corazón: el agente razona, nadie le obliga

Antes de llegar al código, la idea clave: **el nodo agente no "arma la búsqueda" por código**. Simplemente invoca al LLM con las herramientas enlazadas (`llm.bind_tools([buscar_peliculas])`) y un prompt que inyecta el contexto ya extraído por router y psicólogo. Es el propio modelo quien decide:

- **¿Necesito datos reales del catálogo?** → emite una llamada a la herramienta (`tool_calls`) y el grafo la ejecuta.
- **¿No los necesito?** (saludos, dudas) → responde directo y nunca se toca la base de datos.
- **¿La herramienta devolvió vacío?** → puede reintentar una vez con criterios más amplios antes de rendirse.

La descripción de la herramienta es la única guía que tiene el modelo para decidir, por eso está escrita con tanto detalle (cuándo usarla, qué significa cada argumento, qué devuelve).

---

## Cuando algo falla: capas de respaldo

La parte más interesante del grafo es lo que ocurre cuando algo falla — sobre todo porque `qwen2.5:3b` es un modelo pequeño y falla a menudo. Hay respaldos **deterministas (sin coste de LLM)** dentro del propio grafo:

1. **El agente decide parar sin resultados** → `bifurcar_tras_agente` aplica los fallbacks en orden de coste:
   - **Es mood** → `⑦ RESPALDO_MOOD`: vuelve a la herramienta **sin filtros** (lo mejor valorado) para no dejar la pantalla en blanco; el frontend recibe el flag `respaldo_mood`.
   - **Hay heurística** → `⑧ REINTENTAR`: `detectar_termino_catalogo` barre el **mensaje crudo** del usuario contra géneros/actores/títulos reales de la BD (p.ej. "películas con Tom Hanks" mal clasificado como género → devuelve `actor="Tom Hanks"` al parámetro correcto).
   - **Nada de lo anterior** → se redacta con honestidad: "no hay resultados", sin inventar películas.
2. **El agente ni siquiera intenta buscar** con un término válido del router → el mismo `⑧ REINTENTAR` usa directamente ese término (heurística opcional).
3. **Un solo reintento por búsqueda** → la flag `ya_reintentado` acota el bucle; nunca se puede entrar en un loop infinito de reintentos.
4. **Géneros en inglés pese a pedir español** → `_mapear_generos` los traduce a los valores exactos de la BD.
5. **Tildes** → respaldo de comparación normalizada en Python si la SQL no encuentra nada.
6. **Intención irreconocible** → `PEDIR_ACLARACIÓN` con ejemplos de uso.
7. **Repetir la misma búsqueda** → caché TTL en la API: cero llamadas al LLM.

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
│   │   └── tools.py        # Tool del LLM + consultas a la BD + heurísticas
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

Las peticiones **tardan** (~2-4 min la primera vez). No es un descuido: el grafo ejecuta varias llamadas a un **LLM local de 3B parámetros** (router, psicólogo, el agente en cada vuelta de su bucle, redactor) y `qwen2.5:3b` corriendo en CPU no es rápido. Repetir la misma búsqueda o pulsar *OTRAS 10* es inmediato porque hay una caché TTL que evita repetir el LLM.

**La importancia del proyecto no es la velocidad de la app, sino el sistema multiagente y que funcione bien**: que el razonamiento del agente sustituya a la lógica en código, que las herramientas devuelvan datos reales, que haya memoria por sesión (`MemorySaver`), que un error de clasificación se detecte y se corrija dentro del propio grafo, y que nunca se quede la pantalla en blanco. La latencia se reduciría con un modelo remoto o más grande, pero eso queda fuera del alcance de este ejercicio.

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
