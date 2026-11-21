"""Copia los insumos de la prueba a data/raw/ (no versionado).

Uso:
    python scripts/bootstrap_data.py --source "<ruta a Insumos_Prueba_Consultor_IA>"
    # o definir INSUMOS_DIR en .env / variable de entorno
"""
import argparse
import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "data" / "raw"
EXPECTED = ["01_documentos", "02_transcripciones", "03_datos", "04_apis", "05_evaluacion", "06_actualizaciones"]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", default=os.getenv("INSUMOS_DIR"), help="Carpeta Insumos_Prueba_Consultor_IA")
    args = ap.parse_args()
    if not args.source:
        raise SystemExit("Indique --source o la variable INSUMOS_DIR")
    src = Path(args.source)
    missing = [d for d in EXPECTED if not (src / d).is_dir()]
    if missing:
        raise SystemExit(f"Faltan carpetas en {src}: {missing}")

    DEST.mkdir(parents=True, exist_ok=True)
    for d in EXPECTED:
        shutil.copytree(src / d, DEST / d, dirs_exist_ok=True)
    total = sum(1 for _ in DEST.rglob("*") if _.is_file())
    print(f"OK: {total} archivos en {DEST}")


if __name__ == "__main__":
    main()
