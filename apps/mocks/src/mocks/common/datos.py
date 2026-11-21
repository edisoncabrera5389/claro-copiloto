"""Carga de los datos sintéticos (data/raw/04_apis/datos_mock, montado en /data)."""

import json
from datetime import date
from pathlib import Path
from typing import Any


def cargar_json(data_dir: Path, nombre: str) -> Any:
    ruta = data_dir / nombre
    if not ruta.is_file():
        raise RuntimeError(
            f"No se encontró {ruta}. Ejecute scripts/bootstrap_data.py o defina MOCKS_DATA_DIR."
        )
    return json.loads(ruta.read_text(encoding="utf-8"))


def hace_un_anio(hoy: date) -> date:
    try:
        return hoy.replace(year=hoy.year - 1)
    except ValueError:  # 29 de febrero
        return hoy.replace(year=hoy.year - 1, day=28)
