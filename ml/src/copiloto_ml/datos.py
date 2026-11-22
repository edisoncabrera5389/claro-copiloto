"""Carga y limpieza de los datos de entrenamiento (los CSV traen BOM y errores a propósito).

Hallazgos que motivan cada regla (verificados en los insumos):
- tickets.csv: 20 filas duplicadas; solo 164 descripciones únicas en 3.796 tickets; 42 descripciones
  aparecen con más de una categoría (ruido de etiquetas) → voto mayoritario por descripción.
- clientes_churn.csv: 12 clientes duplicados; antigüedad negativa (15), valor mensual 0 (9) y consumo de
  datos imposible (hasta 8.787 GB/mes, 6 casos) → se tratan como faltantes y se imputan en el pipeline.
"""

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

CATEGORIAS = ["soporte_tecnico", "facturacion", "consulta_planes", "cancelacion", "portabilidad"]
NUMERICAS_CHURN = [
    "valor_mensual",
    "antiguedad_meses",
    "dias_mora",
    "tickets_90d",
    "tickets_tecnicos_90d",
    "caidas_servicio_90d",
    "uso_datos_gb_mes",
    "nps_ultimo",
    "ofertas_retencion_12m",
]
CATEGORICAS_CHURN = ["tipo_servicio", "metodo_pago"]
LIMITE_USO_GB = (
    500  # por encima es un error de medición (los planes ilimitados reducen velocidad tras 150 GB)
)


@dataclass
class Reporte:
    """Qué se limpió y por qué (queda en MLflow como evidencia de calidad de datos)."""

    filas_originales: int = 0
    duplicados: int = 0
    correcciones: dict[str, int] = field(default_factory=dict)

    def dict(self) -> dict:
        return {"filas_originales": self.filas_originales, "duplicados": self.duplicados, **self.correcciones}


def cargar_tickets(ruta: Path) -> tuple[pd.DataFrame, Reporte]:
    t = pd.read_csv(ruta, encoding="utf-8-sig")
    rep = Reporte(filas_originales=len(t))
    t = t.drop_duplicates()
    rep.duplicados = rep.filas_originales - len(t)
    t = t.dropna(subset=["descripcion", "categoria"])
    t = t[t.categoria.isin(CATEGORIAS)].copy()
    # Voto mayoritario: la misma nota con etiquetas distintas es error del asesor, no ambigüedad real.
    mayoria = t.groupby("descripcion").categoria.agg(lambda s: s.value_counts().idxmax())
    ruidosas = (t.groupby("descripcion").categoria.nunique() > 1).sum()
    cambiadas = (t.categoria != t.descripcion.map(mayoria)).sum()
    t["categoria_original"] = t.categoria
    t["categoria"] = t.descripcion.map(mayoria)
    rep.correcciones = {
        "descripciones_unicas": int(t.descripcion.nunique()),
        "descripciones_con_ruido": int(ruidosas),
        "etiquetas_corregidas_por_voto": int(cambiadas),
    }
    return t.reset_index(drop=True), rep


def cargar_churn(ruta: Path) -> tuple[pd.DataFrame, Reporte]:
    c = pd.read_csv(ruta, encoding="utf-8-sig")
    rep = Reporte(filas_originales=len(c))
    c = c.drop_duplicates()
    c = c.drop_duplicates(subset="cliente_id", keep="first")
    rep.duplicados = rep.filas_originales - len(c)
    reglas = {
        "antiguedad_negativa": c.antiguedad_meses < 0,
        "valor_mensual_no_positivo": c.valor_mensual <= 0,
        "uso_datos_imposible": c.uso_datos_gb_mes > LIMITE_USO_GB,
    }
    columnas = {
        "antiguedad_negativa": "antiguedad_meses",
        "valor_mensual_no_positivo": "valor_mensual",
        "uso_datos_imposible": "uso_datos_gb_mes",
    }
    for nombre, mascara in reglas.items():
        c.loc[mascara, columnas[nombre]] = np.nan
    rep.correcciones = {k: int(v.sum()) for k, v in reglas.items()}
    rep.correcciones["nps_vacio"] = int(c.nps_ultimo.isna().sum())
    rep.correcciones["ciudad_vacia"] = int(c.ciudad.isna().sum())
    return c.reset_index(drop=True), rep
