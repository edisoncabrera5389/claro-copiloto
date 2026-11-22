"""Memoria corta (Redis, TTL 2 h), propuestas pendientes de confirmación, límite de solicitudes y
memoria larga / auditoría / feedback (MongoDB). Se guarda el texto ENMASCARADO (Ley 1581)."""

import asyncio
import json
import time
import uuid
from typing import Any

from copiloto_api.config import Settings

PENDIENTES = "api:propuestas:pendientes"


class Memoria:
    def __init__(self, s: Settings, redis: Any, db: Any):
        self.s, self.r, self.db = s, redis, db

    # ---------------------------------------------------------------- memoria corta -------
    async def historial(self, sesion_id: str) -> list[dict[str, str]]:
        crudo = await self.r.lrange(f"api:mem:{sesion_id}", -2 * self.s.memoria_turnos, -1)
        return [json.loads(x) for x in crudo]

    async def agregar_turno(self, sesion_id: str, pregunta: str, respuesta: str) -> None:
        clave = f"api:mem:{sesion_id}"
        await self.r.rpush(
            clave,
            json.dumps({"role": "user", "content": pregunta}, ensure_ascii=False),
            json.dumps({"role": "assistant", "content": respuesta}, ensure_ascii=False),
        )
        await self.r.ltrim(clave, -2 * self.s.memoria_turnos, -1)
        await self.r.expire(clave, self.s.memoria_ttl_s)

    # ---------------------------------------------------------------- propuestas ----------
    async def guardar_propuesta(self, datos: dict[str, Any]) -> str:
        """Se guarda en el servidor: al confirmar, el cliente solo envía el id (no altera parámetros)."""
        pid = uuid.uuid4().hex[:12]
        registro = {**datos, "propuesta_id": pid, "creada": time.time()}
        await self.r.set(
            f"api:prop:{pid}",
            json.dumps(registro, ensure_ascii=False, default=str),
            ex=self.s.confirmacion_ttl_s * 2,
        )
        await self.r.zadd(PENDIENTES, {pid: registro["creada"]})
        return pid

    async def propuesta(self, pid: str) -> dict[str, Any] | None:
        crudo = await self.r.get(f"api:prop:{pid}")
        return json.loads(crudo) if crudo else None

    async def tomar_propuesta(self, pid: str) -> dict[str, Any] | None:
        """Atómica (GETDEL): dos confirmaciones simultáneas no ejecutan dos veces."""
        crudo = await self.r.getdel(f"api:prop:{pid}")
        await self.r.zrem(PENDIENTES, pid)
        return json.loads(crudo) if crudo else None

    async def devolver_propuesta(self, datos: dict[str, Any]) -> None:
        await self.r.set(
            f"api:prop:{datos['propuesta_id']}",
            json.dumps(datos, ensure_ascii=False, default=str),
            ex=self.s.confirmacion_ttl_s * 2,
        )
        await self.r.zadd(PENDIENTES, {datos["propuesta_id"]: datos["creada"]})

    async def pendientes(self, usuario: str, rol: str) -> list[dict[str, Any]]:
        salida = []
        for pid in await self.r.zrange(PENDIENTES, 0, -1):
            p = await self.propuesta(pid)
            if p is None:
                await self.r.zrem(PENDIENTES, pid)  # expiró
                continue
            if rol in ("supervisor", "admin") or p.get("usuario") == usuario:
                salida.append(
                    {
                        k: p.get(k)
                        for k in (
                            "propuesta_id",
                            "accion",
                            "resumen",
                            "requiere_rol",
                            "usuario",
                            "sesion_id",
                            "creada",
                        )
                    }
                )
        return salida

    # ---------------------------------------------------------------- límite --------------
    async def permitir(self, usuario: str, recurso: str = "chat") -> bool:
        """Contador por usuario, recurso y minuto: consultar la ficha no consume el cupo del chat."""
        clave = f"api:rl:{recurso}:{usuario}:{int(time.time() // 60)}"
        n = await self.r.incr(clave)
        if n == 1:
            await self.r.expire(clave, 70)
        return n <= self.s.rate_limit_por_min

    # ---------------------------------------------------------------- MongoDB -------------
    async def _insertar(self, coleccion: str, doc: dict[str, Any]) -> None:
        await asyncio.to_thread(self.db[coleccion].insert_one, dict(doc))

    async def auditar_turno(self, doc: dict[str, Any]) -> None:
        await self._insertar("auditoria", doc)

    async def registrar_accion(self, doc: dict[str, Any]) -> None:
        await self._insertar("acciones", doc)

    async def registrar_feedback(self, doc: dict[str, Any]) -> None:
        await self._insertar("feedback", doc)

    async def registrar_escalamiento(self, doc: dict[str, Any]) -> str:
        eid = uuid.uuid4().hex[:12]
        await self._insertar("escalamientos", {**doc, "escalamiento_id": eid, "estado": "abierto"})
        return eid

    async def escalamientos(self, estado: str = "abierto") -> list[dict[str, Any]]:
        def buscar() -> list[dict[str, Any]]:
            return list(self.db["escalamientos"].find({"estado": estado}, {"_id": 0}).sort("fecha", 1))

        return await asyncio.to_thread(buscar)

    async def atender_escalamiento(self, eid: str, supervisor: str, fecha: Any) -> bool:
        r = await asyncio.to_thread(
            self.db["escalamientos"].update_one,
            {"escalamiento_id": eid, "estado": "abierto"},
            {"$set": {"estado": "atendido", "atendido_por": supervisor, "atendido_en": fecha}},
        )
        return r.modified_count == 1

    async def ultimo_turno(self, sesion_id: str, usuario: str) -> dict[str, Any] | None:
        def buscar() -> dict[str, Any] | None:
            return self.db["auditoria"].find_one(
                {"sesion_id": sesion_id, "usuario": usuario},
                {"_id": 0, "turno_id": 1, "cliente_id": 1, "ruta": 1, "motivo": 1},
                sort=[("fecha", -1)],
            )

        return await asyncio.to_thread(buscar)

    async def turno(self, turno_id: str) -> dict[str, Any] | None:
        return await asyncio.to_thread(self.db["auditoria"].find_one, {"turno_id": turno_id}, {"_id": 0})

    async def conversacion(self, sesion_id: str, usuario: str, rol: str) -> list[dict[str, Any]]:
        filtro: dict[str, Any] = {"sesion_id": sesion_id}
        if rol == "asesor":
            filtro["usuario"] = usuario

        def buscar() -> list[dict[str, Any]]:
            campos = {
                "_id": 0,
                "turno_id": 1,
                "fecha": 1,
                "pregunta": 1,
                "respuesta": 1,
                "fuentes": 1,
                "ruta": 1,
                "confianza": 1,
                "propuestas": 1,
            }
            return list(self.db["auditoria"].find(filtro, campos).sort("fecha", 1))

        return await asyncio.to_thread(buscar)
