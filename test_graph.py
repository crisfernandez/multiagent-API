from app.graph.agent import grafo

casos_de_prueba = [
    "Recomiéndame películas de Leonardo DiCaprio",
    "Quiero ver algo de Terror para esta noche",
    "He tenido un día horrible en el trabajo y necesito desconectar y motivarme",
]

for i, mensaje in enumerate(casos_de_prueba):
    print("\n" + "=" * 50)
    print(f"PROBANDO: '{mensaje}'")
    print("=" * 50)

    config = {"configurable": {"thread_id": f"test-{i}"}}
    estado_final = grafo.invoke({"mensaje_usuario": mensaje}, config=config)

    print(f"-> Intención detectada: {estado_final.get('tipo_intencion')}")
    if estado_final.get("termino_busqueda"):
        print(f"-> Término extraído: {estado_final['termino_busqueda']}")
    if estado_final.get("mood_detectado"):
        print(f"-> Mood: {estado_final['mood_detectado']}")
        print(f"-> Keywords: {estado_final.get('keywords', [])}")

    print("\n[RESPUESTA FINAL]:")
    respuesta = estado_final.get("respuesta_final") or "(sin respuesta)"
    print(respuesta[:300] + "...\n")
