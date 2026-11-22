"""Eventos de negocio hacia n8n (SAD: RPA tras escalamiento o acción confirmada).

No bloquea el turno ni la confirmación: se envía en segundo plano con timeout corto; si n8n no responde,
queda en el log y la operación del asesor sigue (el registro de auditoría ya está en MongoDB).
Carga sin PII: identificadores (cliente, factura, ticket), códigos y montos; nunca documento,
celular o correo.
"""

import asyncio
import json
import logging
from typing import Any

log = logging.getLogger("copiloto_api")


class Notificador:
    def __init__(self, url_base: str | None, timeout_s: float = 3.0, cliente: Any = None):
        self.url_base = (url_base or "").rstrip("/")
        if self.url_base and cliente is None:
            import httpx

            cliente = httpx.AsyncClient(timeout=timeout_s)
        self._c = cliente
        self._tareas: set[asyncio.Task] = set()

    def enviar(self, evento: str, datos: dict[str, Any]) -> None:
        """Dispara el webhook `/{evento}` en segundo plano (no espera la respuesta)."""
        if not self.url_base:
            return
        tarea = asyncio.create_task(self._enviar(evento, datos))
        self._tareas.add(tarea)
        tarea.add_done_callback(self._tareas.discard)

    async def _enviar(self, evento: str, datos: dict[str, Any]) -> None:
        try:
            r = await self._c.post(f"{self.url_base}/{evento}", json={"evento": evento, **datos})
            r.raise_for_status()
            log.info(json.dumps({"evento": "n8n_notificado", "flujo": evento, "estado": r.status_code}))
        except Exception as e:  # noqa: BLE001 - n8n es auxiliar: nunca rompe el flujo del asesor
            log.warning(
                json.dumps({"evento": "n8n_no_disponible", "flujo": evento, "error": type(e).__name__})
            )

    async def esperar(self) -> None:
        """Para pruebas y apagado ordenado: espera los envíos pendientes."""
        if self._tareas:
            await asyncio.gather(*self._tareas, return_exceptions=True)
