"""Cliente del ml-service. Nunca bloquea el turno: si el servicio falla o tarda, devuelve None y el agente
sigue con su respaldo (reglas para la intención; sin señal de churn)."""

import logging
from typing import Any

log = logging.getLogger("copiloto_api")


class ClienteML:
    def __init__(self, url: str, timeout_s: float = 1.0, cliente: Any = None):
        if cliente is None:
            import httpx

            cliente = httpx.AsyncClient(base_url=url, timeout=timeout_s)
        self._c = cliente

    async def _post(self, ruta: str, cuerpo: dict[str, Any]) -> dict[str, Any] | None:
        try:
            r = await self._c.post(ruta, json=cuerpo)
            r.raise_for_status()
            return r.json()
        except Exception as e:  # noqa: BLE001 - degradación: el turno continúa sin el modelo
            log.warning("ml-service no disponible (%s): %s", ruta, type(e).__name__)
            return None

    async def intencion(self, texto: str) -> dict[str, Any] | None:
        return await self._post("/intencion", {"texto": texto})

    async def churn(self, ficha: dict[str, Any]) -> dict[str, Any] | None:
        return await self._post("/churn/ficha", {"ficha": ficha})
