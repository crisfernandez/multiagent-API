import threading
import time
from typing import Any, Dict, Optional, Tuple


class CacheTTL:
    """Caché en memoria con caducidad (TTL) y límite de tamaño, segura entre hilos.

    Se usa para no repetir trabajo caro (llamadas al LLM o a TMDB). Cada entrada
    guarda el momento en que se creó; si supera el TTL se descarta al leerla.
    """

    def __init__(self, ttl_segundos: int = 300, max_items: int = 512):
        self._ttl = ttl_segundos
        self._max = max_items
        self._datos: Dict[Any, Tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def obtener(self, clave: Any) -> Optional[Any]:
        with self._lock:
            entrada = self._datos.get(clave)
            if entrada is None:
                return None
            creado, valor = entrada
            if time.time() - creado > self._ttl:
                self._datos.pop(clave, None)
                return None
            return valor

    def guardar(self, clave: Any, valor: Any) -> None:
        with self._lock:
            if len(self._datos) >= self._max:
                # Desaloja la entrada más antigua para no crecer sin límite.
                mas_antiguo = min(self._datos.items(), key=lambda kv: kv[1][0])[0]
                self._datos.pop(mas_antiguo, None)
            self._datos[clave] = (time.time(), valor)
