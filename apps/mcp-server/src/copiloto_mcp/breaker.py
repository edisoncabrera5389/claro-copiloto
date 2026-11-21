"""Circuit breaker por sistema: tras N fallas consecutivas deja de llamar durante un tiempo."""

import time
from collections.abc import Callable
from enum import StrEnum


class EstadoCircuito(StrEnum):
    CERRADO = "cerrado"  # opera normal
    ABIERTO = "abierto"  # falla rápido sin llamar al sistema
    SEMIABIERTO = "semiabierto"  # deja pasar una prueba: si sale bien cierra, si falla reabre


class CircuitBreaker:
    def __init__(self, umbral_fallas: int, abierto_s: float, reloj: Callable[[], float] = time.monotonic):
        self.umbral_fallas = umbral_fallas
        self.abierto_s = abierto_s
        self._reloj = reloj
        self.estado = EstadoCircuito.CERRADO
        self.fallas_consecutivas = 0
        self._abierto_desde = 0.0
        self.aperturas = 0

    def permite(self) -> bool:
        if self.estado is EstadoCircuito.ABIERTO and self.segundos_para_reintentar() == 0:
            self.estado = EstadoCircuito.SEMIABIERTO
        return self.estado is not EstadoCircuito.ABIERTO

    def registrar_exito(self) -> None:
        self.estado = EstadoCircuito.CERRADO
        self.fallas_consecutivas = 0

    def registrar_falla(self) -> None:
        self.fallas_consecutivas += 1
        if self.estado is EstadoCircuito.SEMIABIERTO or self.fallas_consecutivas >= self.umbral_fallas:
            self.estado = EstadoCircuito.ABIERTO
            self._abierto_desde = self._reloj()
            self.aperturas += 1

    def segundos_para_reintentar(self) -> float:
        if self.estado is not EstadoCircuito.ABIERTO:
            return 0.0
        return max(0.0, self.abierto_s - (self._reloj() - self._abierto_desde))

    def resumen(self) -> dict:
        return {
            "estado": self.estado.value,
            "fallas_consecutivas": self.fallas_consecutivas,
            "aperturas": self.aperturas,
            "reintentar_en_s": round(self.segundos_para_reintentar(), 1),
        }
