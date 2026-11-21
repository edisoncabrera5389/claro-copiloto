"""CLI de la ingesta.

python -m ingesta watcher                 # vigila la carpeta y publica eventos
python -m ingesta worker                  # consume eventos y procesa
python -m ingesta procesar <archivo>...   # procesa directo (sin cola); --forzar reindexa igual contenido
python -m ingesta buscar "consulta" [-k 5] [--todas-las-versiones] [--transcripciones]
python -m ingesta estado                  # documentos, versiones vigentes, frescura
python -m ingesta reintentar              # devuelve los eventos fallidos (dead-letter) a la cola
python -m ingesta revertir <doc_id> <ver> # retira una versión (ensayo de la demo de frescura)
python -m ingesta salud --rol worker      # healthcheck del contenedor (latido reciente)
"""

import argparse
import json
import logging
import os
import socket
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ingesta.config import Settings


def _redis(s: Settings) -> Any:
    import redis

    # El timeout de lectura debe superar el bloqueo de XREADGROUP (5 s): con el valor por defecto de
    # redis-py 8 la espera de eventos se cortaba como error y el worker se reiniciaba.
    return redis.Redis.from_url(
        s.redis_url, decode_responses=True, socket_timeout=30, health_check_interval=30
    )


def _dependencias(s: Settings, con_pipeline: bool = True) -> dict[str, Any]:
    from pymongo import MongoClient
    from qdrant_client import QdrantClient

    from ingesta.embeddings import OpenAIEmbedder
    from ingesta.indice import IndiceQdrant
    from ingesta.registro import Registro

    if s.openai_api_key is None:
        raise SystemExit("Falta OPENAI_API_KEY para los embeddings")
    embedder = OpenAIEmbedder(
        s.openai_api_key.get_secret_value(), s.embedding_model, s.embedding_dim, s.openai_base_url
    )
    indice = IndiceQdrant(QdrantClient(url=s.qdrant_url, timeout=30), s.coleccion, s.embedding_dim)
    registro = Registro(MongoClient(s.mongo_url, serverSelectionTimeoutMS=5000)[s.mongo_db])
    deps: dict[str, Any] = {
        "redis": _redis(s),
        "indice": indice,
        "registro": registro,
        "embedder": embedder,
    }
    if con_pipeline:
        from ingesta.pii import Anonimizador
        from ingesta.pipeline import Pipeline

        indice.asegurar()
        registro.asegurar()
        deps["pipeline"] = Pipeline(s, indice, registro, embedder, Anonimizador())
    return deps


def _json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2, default=str)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("presidio-analyzer").setLevel(logging.ERROR)  # avisos de reconocedores de otros idiomas
    for ruidoso in ("httpx", "openai", "faster_whisper"):
        logging.getLogger(ruidoso).setLevel(logging.WARNING)
    ap = argparse.ArgumentParser(prog="ingesta")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("watcher")
    sub.add_parser("worker")
    p = sub.add_parser("procesar")
    p.add_argument("archivos", nargs="+", type=Path)
    p.add_argument("--forzar", action="store_true", help="Reindexa aunque el contenido no haya cambiado")
    b = sub.add_parser("buscar")
    b.add_argument("consulta")
    b.add_argument("-k", type=int, default=5)
    b.add_argument("--todas-las-versiones", action="store_true")
    b.add_argument("--transcripciones", action="store_true")
    sub.add_parser("estado")
    sub.add_parser("reintentar")
    rv = sub.add_parser("revertir")
    rv.add_argument("doc_id")
    rv.add_argument("version")
    sa = sub.add_parser("salud")
    sa.add_argument("--rol", choices=["watcher", "worker"], required=True)
    sa.add_argument("--max-s", type=float, default=90)
    args = ap.parse_args()
    s = Settings()

    if args.cmd == "salud":
        archivo = s.latido_dir / f"ingesta-{args.rol}.latido"
        if not archivo.is_file():
            return 1
        edad = (
            datetime.now(UTC) - datetime.fromisoformat(archivo.read_text(encoding="utf-8"))
        ).total_seconds()
        return 0 if edad <= args.max_s else 1

    from ingesta.cola import VISTOS, Watcher, Worker, reencolar_fallidos

    if args.cmd == "watcher":
        Watcher(s, _redis(s)).correr()
    if args.cmd == "reintentar":
        rutas = reencolar_fallidos(s, _redis(s))
        print(_json({"reencolados": len(rutas), "rutas": rutas}))
        return 0
    deps = _dependencias(s, con_pipeline=args.cmd in ("worker", "procesar", "revertir"))
    if args.cmd == "revertir":
        r = deps["pipeline"].revertir(args.doc_id, args.version)
        # El watcher olvida esos archivos: si vuelven a caer en la carpeta, se procesan de nuevo.
        vistos = deps["redis"].hkeys(VISTOS)
        olvidados = [k for k in vistos if any(k.endswith(f) for f in r["fuentes"])]
        if olvidados:
            deps["redis"].hdel(VISTOS, *olvidados)
        print(_json(r | {"olvidados_por_watcher": olvidados}))
        return 0
    if args.cmd == "worker":
        consumidor = os.getenv("HOSTNAME") or socket.gethostname()
        Worker(s, deps["redis"], deps["pipeline"].procesar, consumidor).correr()
    elif args.cmd == "procesar":
        for archivo in args.archivos:
            r = deps["pipeline"].procesar(archivo, forzar=args.forzar)
            print(
                _json(
                    {
                        k: r.get(k)
                        for k in (
                            "fuente",
                            "resultado",
                            "doc_id",
                            "version",
                            "vigente",
                            "fragmentos",
                            "pii",
                            "frescura_s",
                        )
                    }
                )
            )
    elif args.cmd == "buscar":
        for i, h in enumerate(
            deps["indice"].buscar(
                args.consulta, deps["embedder"], args.k, not args.todas_las_versiones, args.transcripciones
            ),
            1,
        ):
            estado = "" if h["vigente"] else " (NO vigente)"
            print(
                f"[{i}] {h['score']:.3f}  {h['fuente']} · v{h['version']}{estado} · {h.get('seccion') or ''}"
            )
            print("    " + h["texto"][:220].replace("\n", " ") + "\n")
    elif args.cmd == "estado":
        reg = deps["registro"]
        print(
            _json(
                {
                    "documentos": reg.resumen(),
                    "frescura": reg.frescura(),
                    "fragmentos_vigentes": deps["indice"].contar(vigente=True),
                    "eventos_fallidos": deps["redis"].xlen(s.stream_fallidos),
                }
            )
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
