"""Carpeta vigilada → Redis Streams → workers.

En Azure: Blob Storage + Event Grid → Queue → Container Apps Job.

- Watcher: polling (en Docker Desktop sobre Windows los eventos inotify de carpetas montadas no son
  confiables). Publica un evento cuando un archivo nuevo o modificado tiene tamaño y fecha ESTABLES en
  dos escaneos seguidos (evita leer archivos a medio copiar). Lo ya visto se guarda en Redis, así un
  reinicio no reprocesa todo (y el pipeline es idempotente por hash de todos modos).
- Worker: grupo de consumidores (escala horizontal agregando réplicas). Reintenta hasta max_intentos
  y luego envía el evento a `ingesta:fallidos` (dead-letter) para revisión.
"""

import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from redis.exceptions import RedisError

from ingesta.config import Settings
from ingesta.identificacion import identificar

log = logging.getLogger("ingesta")
VISTOS = "ingesta:vistos"


def latido(s: Settings, rol: str) -> None:
    (s.latido_dir / f"ingesta-{rol}.latido").write_text(datetime.now(UTC).isoformat(), encoding="utf-8")


class Watcher:
    def __init__(self, s: Settings, redis: Any, reloj: Callable[[], datetime] = lambda: datetime.now(UTC)):
        self.s, self.r, self._reloj = s, redis, reloj
        # ruta relativa -> (firma observada, momento en que se vio por primera vez ese cambio)
        self._pendientes: dict[str, tuple[str, datetime]] = {}

    def _firma(self, p: Path) -> str:
        st = p.stat()
        return f"{st.st_size}:{st.st_mtime_ns}"

    def escanear(self) -> list[dict[str, str]]:
        publicados = []
        ahora = self._reloj()
        nuevos_pendientes: dict[str, tuple[str, datetime]] = {}
        for p in sorted(self.s.inbox_dir.rglob("*")):
            if not p.is_file() or identificar(p) is None:
                continue
            rel = p.relative_to(self.s.inbox_dir).as_posix()
            firma = self._firma(p)
            if self.r.hget(VISTOS, rel) == firma:
                continue
            previo = self._pendientes.get(rel)
            if previo is None or previo[0] != firma:  # primera vez que se ve así: esperar a que se estabilice
                nuevos_pendientes[rel] = (firma, ahora)
                continue
            # La frescura se mide desde que se VIO el archivo, no desde que se publicó (incluye la espera).
            evento = {"ruta": rel, "t_detectado": previo[1].isoformat(), "firma": firma, "intento": "1"}
            self.r.xadd(self.s.stream, evento)
            self.r.hset(VISTOS, rel, firma)
            publicados.append(evento)
            log.info('{"evento": "detectado", "ruta": "%s"}', rel)
        self._pendientes = nuevos_pendientes
        return publicados

    def correr(self) -> None:  # pragma: no cover - bucle infinito
        self.s.inbox_dir.mkdir(parents=True, exist_ok=True)
        log.info(
            '{"evento": "watcher_iniciado", "inbox": "%s", "poll_s": %s}', self.s.inbox_dir, self.s.poll_s
        )
        while True:
            try:
                self.escanear()
                latido(self.s, "watcher")
            except (RedisError, OSError) as e:
                log.warning('{"evento": "redis_no_disponible", "error": "%s"}', type(e).__name__)
            time.sleep(self.s.poll_s)


def reencolar_fallidos(s: Settings, redis: Any) -> list[str]:
    """Devuelve los eventos de la dead-letter a la cola principal (tras corregir la causa)."""
    rutas = []
    for msg_id, campos in redis.xrange(s.stream_fallidos):
        evento = {k: v for k, v in campos.items() if k != "error"} | {"intento": "1"}
        redis.xadd(s.stream, evento)
        redis.xdel(s.stream_fallidos, msg_id)
        rutas.append(campos.get("ruta", "?"))
    return rutas


class Worker:
    def __init__(
        self,
        s: Settings,
        redis: Any,
        procesar: Callable[..., dict[str, Any]],
        consumidor: str = "worker-1",
        metricas: Any = None,
    ):
        self.s, self.r, self._procesar, self.consumidor = s, redis, procesar, consumidor
        self.metricas = metricas

    def estado_cola(self) -> dict[str, float]:
        """Para Prometheus: eventos sin leer por el grupo (lag) y eventos en la dead-letter."""
        grupos = {g["name"]: g for g in self.r.xinfo_groups(self.s.stream)}
        lag = grupos.get(self.s.grupo, {}).get("lag")
        return {"pendientes": float(lag or 0), "fallidos": float(self.r.xlen(self.s.stream_fallidos))}

    def asegurar_grupo(self) -> None:
        try:
            self.r.xgroup_create(self.s.stream, self.s.grupo, id="0", mkstream=True)
        except Exception as e:  # BUSYGROUP: ya existe
            if "BUSYGROUP" not in str(e):
                raise

    def procesar_lote(self, bloqueo_ms: int = 5000, cantidad: int = 10) -> int:
        respuesta = self.r.xreadgroup(
            self.s.grupo, self.consumidor, {self.s.stream: ">"}, count=cantidad, block=bloqueo_ms
        )
        n = 0
        for _, mensajes in respuesta or []:
            for msg_id, campos in mensajes:
                n += 1
                self._atender(msg_id, campos)
        return n

    def _atender(self, msg_id: str, campos: dict[str, str]) -> None:
        intento = int(campos.get("intento", "1"))
        try:
            t_det = datetime.fromisoformat(campos["t_detectado"])
            r = self._procesar(self.s.inbox_dir / campos["ruta"], t_detectado=t_det, evento_id=msg_id)
            log.info(
                '{"evento": "procesado", "ruta": "%s", "resultado": "%s", "version": "%s", '
                '"fragmentos": %s, "frescura_s": %s}',
                campos["ruta"],
                r.get("resultado"),
                r.get("version"),
                r.get("fragmentos", 0),
                r.get("frescura_s"),
            )
            if self.metricas:
                self.metricas.documento(r.get("resultado") or "?", r.get("frescura_s"))
        except Exception as e:
            if self.metricas:
                self.metricas.error()
            destino = self.s.stream if intento < self.s.max_intentos else self.s.stream_fallidos
            self.r.xadd(
                destino, {**campos, "intento": str(intento + 1), "error": f"{type(e).__name__}: {e}"[:500]}
            )
            log.warning(
                '{"evento": "error", "ruta": "%s", "intento": %s, "destino": "%s", "error": "%s"}',
                campos.get("ruta"),
                intento,
                destino,
                type(e).__name__,
            )
        finally:
            self.r.xack(self.s.stream, self.s.grupo, msg_id)

    def ciclo(self) -> int:
        """Una vuelta del bucle: un corte de Redis se registra y se reintenta, no tumba el proceso."""
        try:
            n = self.procesar_lote()
        except (RedisError, OSError) as e:  # las de redis-py no heredan de ConnectionError/TimeoutError
            log.warning('{"evento": "redis_no_disponible", "error": "%s"}', type(e).__name__)
            time.sleep(2)
            return 0
        latido(self.s, "worker")
        return n

    def correr(self) -> None:  # pragma: no cover - bucle infinito
        self.asegurar_grupo()
        log.info('{"evento": "worker_iniciado", "consumidor": "%s"}', self.consumidor)
        while True:
            self.ciclo()
