"""Autenticación JWT por rol (asesor, supervisor, admin). En producción se reemplaza por SSO corporativo."""

import hmac
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from copiloto_api.config import Settings

ROLES = ("asesor", "supervisor", "admin")
_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Usuario:
    id: str
    rol: str
    nombre: str

    def dict(self) -> dict[str, str]:
        return {"id": self.id, "rol": self.rol, "nombre": self.nombre}


def usuarios(s: Settings) -> dict[str, Usuario]:
    salida = {}
    for item in s.usuarios_demo.split(","):
        uid, rol, nombre = (p.strip() for p in item.split(":", 2))
        if rol in ROLES:
            salida[uid] = Usuario(uid, rol, nombre)
    return salida


def autenticar(s: Settings, usuario: str, password: str) -> Usuario | None:
    u = usuarios(s).get(usuario)
    ok = hmac.compare_digest(password.encode(), s.demo_password.get_secret_value().encode())
    return u if u and ok else None


def emitir_jwt(s: Settings, u: Usuario) -> str:
    ahora = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": u.id,
            "rol": u.rol,
            "nombre": u.nombre,
            "iat": ahora,
            "exp": ahora + timedelta(minutes=s.jwt_expira_min),
        },
        s.jwt_secret.get_secret_value(),
        algorithm="HS256",
    )


def usuario_actual(
    request: Request, cred: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]
) -> Usuario:
    if cred is None:
        raise HTTPException(401, "Falta el token de acceso", headers={"WWW-Authenticate": "Bearer"})
    s: Settings = request.app.state.settings
    try:
        datos = jwt.decode(cred.credentials, s.jwt_secret.get_secret_value(), algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "La sesión expiró") from None
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Token inválido") from None
    if datos.get("rol") not in ROLES:
        raise HTTPException(403, "Rol no autorizado")
    return Usuario(datos["sub"], datos["rol"], datos.get("nombre", datos["sub"]))
