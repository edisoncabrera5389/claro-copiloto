"""Cliente HTTP resiliente hacia CRM y Facturación.

Política por intento:
- 2xx → éxito.  4xx de negocio (400/403/404/409) → `ErrorNegocio`, sin reintento.
- 429 → espera `Retry-After` si es corto (≤ retry_after_max_s) y reintenta; si es largo, falla rápido.
  No cuenta como falla del circuito: el sistema está sano, solo nos limita.
- 503, 5xx, timeouts y errores de conexión → backoff exponencial con jitter y cuentan para el circuito.
- POST (con efecto): solo se reintenta cuando hay garantía de que no se ejecutó: 503 (el sistema lo
  rechaza antes de procesar) o error de conexión. Un timeout o un 500 en POST NO se reintenta.
"""

import asyncio
import json
import random
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from copiloto_mcp.breaker import CircuitBreaker
from copiloto_mcp.config import Settings


class ErrorSistema(Exception):
    def __init__(
        self,
        sistema: str,
        codigo: str,
        mensaje: str,
        status: int | None = None,
        retry_after_s: float | None = None,
        sin_efecto: bool = True,
    ):
        super().__init__(f"{codigo}: {mensaje}")
        self.sistema = sistema
        self.codigo = codigo
        self.mensaje = mensaje
        self.status = status
        self.retry_after_s = retry_after_s
        # True si hay certeza de que una escritura NO se aplicó (permite reintentar sin duplicar).
        self.sin_efecto = sin_efecto


class ErrorNegocio(ErrorSistema):
    """El sistema respondió y rechazó la solicitud (validación, no encontrado, regla de negocio)."""


class SistemaNoDisponible(ErrorSistema):
    """No se obtuvo respuesta útil: circuito abierto, límite, 5xx, timeout o sin conexión."""


def _cuerpo_error(r: httpx.Response) -> tuple[str | None, str]:
    try:
        j = r.json()
        return j.get("codigo"), j.get("mensaje", r.reason_phrase)
    except (json.JSONDecodeError, AttributeError):
        return None, r.reason_phrase


class ClienteSistema:
    def __init__(
        self,
        nombre: str,
        base_url: str,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        dormir: Callable[[float], Awaitable[None]] = asyncio.sleep,
        aleatorio: Callable[[], float] = random.random,
        reloj: Callable[[], float] = time.monotonic,
    ):
        self.nombre = nombre
        self.s = settings
        self._dormir = dormir
        self._aleatorio = aleatorio
        self.breaker = CircuitBreaker(settings.breaker_fallas, settings.breaker_abierto_s, reloj)
        self.reintentos_realizados = 0
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"X-API-Key": settings.mocks_api_key.get_secret_value(), "Accept": "application/json"},
            timeout=httpx.Timeout(settings.http_timeout_s, connect=min(2.0, settings.http_timeout_s)),
            transport=transport,
        )

    async def cerrar(self) -> None:
        await self._http.aclose()

    async def get(self, ruta: str, params: dict[str, Any] | None = None) -> Any:
        return await self._solicitar("GET", ruta, params=params)

    async def post(self, ruta: str, cuerpo: dict[str, Any]) -> Any:
        return await self._solicitar("POST", ruta, cuerpo=cuerpo)

    def _espera_backoff(self, intento: int) -> float:
        tope = min(self.s.backoff_max_s, self.s.backoff_base_s * 2 ** (intento - 1))
        return tope * (0.5 + self._aleatorio() / 2)  # "equal jitter": evita reintentos sincronizados

    async def _solicitar(
        self,
        metodo: str,
        ruta: str,
        params: dict[str, Any] | None = None,
        cuerpo: dict[str, Any] | None = None,
    ) -> Any:
        idempotente = metodo == "GET"
        # Un trace-id por operación lógica (todos sus reintentos), propagado en W3C traceparent.
        cabeceras = {"traceparent": f"00-{uuid.uuid4().hex}-{uuid.uuid4().hex[:16]}-01"}
        ultimo: ErrorSistema | None = None

        for intento in range(1, self.s.reintentos + 1):
            es_ultimo = intento == self.s.reintentos
            if not self.breaker.permite():
                espera = self.breaker.segundos_para_reintentar()
                raise SistemaNoDisponible(
                    self.nombre,
                    "CIRCUITO_ABIERTO",
                    f"{self.nombre} no disponible temporalmente; reintente en {espera:.0f} s",
                    retry_after_s=espera,
                )
            if intento > 1:
                self.reintentos_realizados += 1
            try:
                r = await self._http.request(metodo, ruta, params=params, json=cuerpo, headers=cabeceras)
            except (httpx.ConnectError, httpx.ConnectTimeout):
                self.breaker.registrar_falla()
                ultimo = SistemaNoDisponible(
                    self.nombre, "SIN_CONEXION", f"No hay conexión con {self.nombre}"
                )
            except httpx.TimeoutException:
                self.breaker.registrar_falla()
                ultimo = SistemaNoDisponible(
                    self.nombre, "TIMEOUT", f"{self.nombre} no respondió a tiempo", sin_efecto=False
                )
                if not idempotente:
                    raise ultimo from None  # pudo ejecutarse: no se reintenta una escritura
            else:
                if r.status_code < 400:
                    self.breaker.registrar_exito()
                    return r.json() if r.content else None

                codigo, mensaje = _cuerpo_error(r)
                if r.status_code == 429:
                    retry_after = float(r.headers.get("Retry-After", "1") or 1)
                    ultimo = SistemaNoDisponible(
                        self.nombre,
                        codigo or "LIMITE_EXCEDIDO",
                        f"{self.nombre} limitó las solicitudes; reintente en {retry_after:.0f} s",
                        status=429,
                        retry_after_s=retry_after,
                    )
                    if retry_after > self.s.retry_after_max_s or es_ultimo:
                        raise ultimo
                    await self._dormir(retry_after)
                    continue
                if r.status_code >= 500:
                    self.breaker.registrar_falla()
                    sin_efecto = r.status_code == 503
                    ultimo = SistemaNoDisponible(
                        self.nombre,
                        codigo or "ERROR_SISTEMA",
                        mensaje,
                        status=r.status_code,
                        sin_efecto=sin_efecto,
                    )
                    if not idempotente and not sin_efecto:
                        raise ultimo
                else:
                    self.breaker.registrar_exito()  # el sistema respondió: está sano
                    raise ErrorNegocio(
                        self.nombre, codigo or "ERROR_SOLICITUD", mensaje, status=r.status_code
                    )

            if not es_ultimo:
                await self._dormir(self._espera_backoff(intento))

        assert ultimo is not None  # noqa: S101 - el bucle siempre asigna antes de salir
        raise ultimo
