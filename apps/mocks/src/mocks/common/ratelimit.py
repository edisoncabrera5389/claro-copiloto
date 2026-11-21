"""Límite de solicitudes por clave con ventana deslizante (en memoria, un proceso)."""

import math
import time
from collections import defaultdict, deque
from collections.abc import Callable


class RateLimiter:
    def __init__(self, limite: int, ventana_s: float = 60.0, reloj: Callable[[], float] = time.monotonic):
        self.limite = limite
        self.ventana_s = ventana_s
        self._reloj = reloj
        self._eventos: dict[str, deque[float]] = defaultdict(deque)

    def consumir(self, clave: str) -> tuple[bool, int, int]:
        """Registra una solicitud. Devuelve (permitida, retry_after_s, restantes)."""
        ahora = self._reloj()
        eventos = self._eventos[clave]
        while eventos and eventos[0] <= ahora - self.ventana_s:
            eventos.popleft()
        if len(eventos) >= self.limite:
            # Segundos hasta que la solicitud más antigua salga de la ventana.
            retry_after = max(1, math.ceil(eventos[0] + self.ventana_s - ahora))
            return False, retry_after, 0
        eventos.append(ahora)
        return True, 0, self.limite - len(eventos)

    def reiniciar(self) -> None:
        self._eventos.clear()
