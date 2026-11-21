"""Siembra la carpeta vigilada (data/inbox) con el corpus de la prueba para la carga inicial.

Copia data/raw/01_documentos (DOCX y PDF: la ingesta resuelve los duplicados), las 50 transcripciones
y los 3 audios. NO copia el catálogo v2 (06_actualizaciones): ese se deja caer durante la demo de
frescura con `--catalogo-v2`.

    py -3.13 scripts/sembrar_inbox.py                 # carga inicial
    py -3.13 scripts/sembrar_inbox.py --sin-audios    # sin Whisper (más rápido)
    py -3.13 scripts/sembrar_inbox.py --catalogo-v2   # demo de frescura: llega la versión 2.0
    py -3.13 scripts/sembrar_inbox.py --quitar-v2     # ensayo: retira la v2 (vuelve a vigente la v1.0)
    py -3.13 scripts/sembrar_inbox.py --limpiar       # vacía data/inbox (no toca el índice)
"""

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
INBOX = ROOT / "data" / "inbox"


def copiar(origen: Path, destino: Path) -> bool:
    destino.parent.mkdir(parents=True, exist_ok=True)
    if destino.exists() and destino.read_bytes() == origen.read_bytes():
        return False
    shutil.copyfile(origen, destino)  # copyfile (no copy2): la fecha de modificación es la de la llegada
    return True


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sin-audios", action="store_true")
    ap.add_argument("--catalogo-v2", action="store_true", help="Solo copia el catálogo v2 (demo de frescura)")
    ap.add_argument(
        "--quitar-v2", action="store_true", help="Retira la v2 del índice y de la carpeta (ensayo)"
    )
    ap.add_argument("--limpiar", action="store_true")
    args = ap.parse_args()
    if not RAW.is_dir():
        print("Faltan los insumos en data/raw: ejecute scripts/bootstrap_data.py")
        return 2

    if args.limpiar:
        for p in INBOX.iterdir() if INBOX.is_dir() else []:
            if p.name != ".gitkeep":
                shutil.rmtree(p) if p.is_dir() else p.unlink()
        print(f"data/inbox vaciada ({INBOX})")
        return 0

    if args.quitar_v2:
        destino = INBOX / "actualizaciones" / "Catalogo_Planes_Claro_2026_v2.pdf"
        destino.unlink(missing_ok=True)
        cmd = [
            "docker",
            "compose",
            "exec",
            "-T",
            "ingesta-worker",
            "python",
            "-m",
            "ingesta",
            "revertir",
            "catalogo_planes_claro_2026",
            "2.0",
        ]
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=False)  # noqa: S603
        print(r.stdout.strip() or r.stderr.strip())
        print(
            "Listo para repetir la demo: la v1.0 vuelve a estar vigente."
            if r.returncode == 0
            else "Falló el reverso"
        )
        return r.returncode

    if args.catalogo_v2:
        origen = RAW / "06_actualizaciones" / "Catalogo_Planes_Claro_2026_v2.pdf"
        copiar(origen, INBOX / "actualizaciones" / origen.name)
        print(f"{time.strftime('%H:%M:%S')}  Copiado {origen.name} a data/inbox/actualizaciones/")
        print("Siga el progreso:  docker compose logs -f ingesta-worker")
        return 0

    pares = [
        (p, INBOX / "documentos" / p.relative_to(RAW / "01_documentos"))
        for p in (RAW / "01_documentos").rglob("*")
        if p.is_file()
    ]
    pares += [
        (p, INBOX / "transcripciones" / p.name)
        for p in (RAW / "02_transcripciones" / "llamadas").glob("*.txt")
    ]
    if not args.sin_audios:
        pares += [
            (p, INBOX / "audios" / p.name) for p in (RAW / "02_transcripciones" / "audios").glob("*.wav")
        ]
    nuevos = sum(copiar(o, d) for o, d in sorted(pares))
    print(f"{nuevos} archivos nuevos o cambiados de {len(pares)} en data/inbox (el resto ya estaba igual)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
