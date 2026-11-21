"""Tokens de confirmación para acciones con efecto (human-in-the-loop verificable).

La API los emite cuando el asesor pulsa "Confirmar" en la UI; el MCP los verifica antes de cada POST.
El LLM nunca ve el secreto, así que no puede fabricar un token: aunque el agente intente ejecutar una
escritura por su cuenta, el MCP la rechaza.

Formato: base64url(payload_json) "." base64url(HMAC-SHA256(secreto, base64url(payload_json)))
payload = {"v": 1, "acc": accion, "h": huella, "sub": asesor_id, "rol": "asesor"|"supervisor",
           "iat": epoch, "exp": epoch, "jti": uuid}
huella  = sha256 de json.dumps({"accion": accion, "parametros": parametros}, sort_keys=True,
          separators=(",", ":"), ensure_ascii=False)  → el token solo sirve para ESOS parámetros.

Uso único: el `jti` se marca como consumido (en memoria; en producción, Redis con TTL = exp).

CLI para la demo mientras no exista la API (lee MCP_CONFIRMACION_SECRET):
    python -m copiloto_mcp.confirmacion --accion crearTicket --asesor A-001 \
        --parametros '{"cliente_id": "C-1013", ...}'        # los "parametros" de la propuesta
"""

import argparse
import base64
import hashlib
import hmac
import json
import os
import sys
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

ROLES = ("asesor", "supervisor")


class ConfirmacionInvalida(Exception):
    def __init__(self, codigo: str, mensaje: str):
        super().__init__(f"{codigo}: {mensaje}")
        self.codigo = codigo
        self.mensaje = mensaje


@dataclass(frozen=True)
class Confirmacion:
    accion: str
    asesor_id: str
    rol: str
    jti: str
    exp: float


def _b64(datos: bytes) -> str:
    return base64.urlsafe_b64encode(datos).rstrip(b"=").decode()


def _desb64(texto: str) -> bytes:
    return base64.urlsafe_b64decode(texto + "=" * (-len(texto) % 4))


def huella(accion: str, parametros: dict[str, Any]) -> str:
    canonico = json.dumps(
        {"accion": accion, "parametros": parametros},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonico.encode()).hexdigest()


class Confirmaciones:
    def __init__(self, secreto: str, ttl_s: int = 300, reloj: Callable[[], float] = time.time):
        self._secreto = secreto.encode()
        self.ttl_s = ttl_s
        self._reloj = reloj
        self._consumidos: dict[str, float] = {}  # jti -> exp

    def _firma(self, cuerpo: str) -> str:
        return _b64(hmac.new(self._secreto, cuerpo.encode(), hashlib.sha256).digest())

    def emitir(self, accion: str, parametros: dict[str, Any], asesor_id: str, rol: str = "asesor") -> str:
        """Lo usa la API (o la CLI de demo). Nunca se expone como tool."""
        if rol not in ROLES:
            raise ValueError(f"Rol inválido: {rol}")
        ahora = self._reloj()
        payload = {
            "v": 1,
            "acc": accion,
            "h": huella(accion, parametros),
            "sub": asesor_id,
            "rol": rol,
            "iat": int(ahora),
            "exp": int(ahora + self.ttl_s),
            "jti": uuid.uuid4().hex,
        }
        cuerpo = _b64(json.dumps(payload, separators=(",", ":")).encode())
        return f"{cuerpo}.{self._firma(cuerpo)}"

    def verificar(self, token: str, accion: str, parametros: dict[str, Any]) -> Confirmacion:
        try:
            cuerpo, firma = token.strip().split(".")
            if not hmac.compare_digest(firma, self._firma(cuerpo)):
                raise ValueError("firma")
            p = json.loads(_desb64(cuerpo))
        except (ValueError, json.JSONDecodeError):
            raise ConfirmacionInvalida(
                "CONFIRMACION_INVALIDA", "El token de confirmación no es válido"
            ) from None
        if p.get("v") != 1 or p.get("rol") not in ROLES:
            raise ConfirmacionInvalida("CONFIRMACION_INVALIDA", "Versión o rol del token no reconocido")
        if self._reloj() >= p["exp"]:
            raise ConfirmacionInvalida(
                "CONFIRMACION_EXPIRADA", "La confirmación expiró; el asesor debe confirmar de nuevo"
            )
        if p["acc"] != accion or not hmac.compare_digest(p["h"], huella(accion, parametros)):
            raise ConfirmacionInvalida(
                "CONFIRMACION_NO_COINCIDE",
                "El token no corresponde a esta acción o sus parámetros cambiaron después de la confirmación",
            )
        self._purgar()
        if p["jti"] in self._consumidos:
            raise ConfirmacionInvalida("CONFIRMACION_YA_USADA", "Esta confirmación ya se utilizó")
        return Confirmacion(accion=accion, asesor_id=p["sub"], rol=p["rol"], jti=p["jti"], exp=p["exp"])

    def consumir(self, c: Confirmacion) -> None:
        self._consumidos[c.jti] = c.exp

    def liberar(self, c: Confirmacion) -> None:
        """Devuelve el token si la escritura NO se aplicó (sistema caído): el asesor no reconfirma."""
        self._consumidos.pop(c.jti, None)

    def _purgar(self) -> None:
        ahora = self._reloj()
        for jti in [j for j, exp in self._consumidos.items() if exp <= ahora]:
            del self._consumidos[jti]


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Emite un token de confirmación (solo demo; en producción lo emite la API)"
    )
    ap.add_argument(
        "--accion", required=True, choices=["crearTicket", "registrarOfertaRetencion", "aplicarAjuste"]
    )
    ap.add_argument("--parametros", required=True, help="JSON con los 'parametros' de la propuesta")
    ap.add_argument("--asesor", required=True)
    ap.add_argument("--rol", default="asesor", choices=ROLES)
    args = ap.parse_args()
    secreto = os.getenv("MCP_CONFIRMACION_SECRET", "")
    if len(secreto) < 32:
        print("Defina MCP_CONFIRMACION_SECRET (mínimo 32 caracteres)", file=sys.stderr)
        return 2
    ttl = int(os.getenv("MCP_CONFIRMACION_TTL_S", "300"))
    print(
        Confirmaciones(secreto, ttl).emitir(args.accion, json.loads(args.parametros), args.asesor, args.rol)
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
