"""Variables del modelo de churn a partir de la ficha del CRM (ya sin PII, tal como la entrega el MCP).

El modelo se entrenó con clientes_churn.csv (CL-xxxxx); los clientes del CRM de la demo (C-xxxx) traen
casi las mismas variables. Las que el CRM no tiene (NPS, uso de datos, caídas de red, método de pago) van
como faltantes: el pipeline las imputa igual que en entrenamiento, sin inventar valores.
"""

from datetime import date, timedelta
from typing import Any

NUMERICAS = [
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
CATEGORICAS = ["tipo_servicio", "metodo_pago"]
COLUMNAS = NUMERICAS + CATEGORICAS
NO_DISPONIBLES_EN_CRM = ["caidas_servicio_90d", "uso_datos_gb_mes", "nps_ultimo", "metodo_pago"]


def desde_ficha(ficha: dict[str, Any], hoy: date) -> dict[str, Any]:
    activos = [s for s in ficha.get("servicios", []) if s.get("estado", "activo") == "activo"]
    tipos = {s.get("tipo") for s in activos}
    tipo = "convergente" if {"hogar", "movil"} <= tipos else (tipos.pop() if len(tipos) == 1 else None)
    desde = hoy - timedelta(days=90)
    tickets = [t for t in ficha.get("tickets_recientes", []) if date.fromisoformat(t["fecha"]) >= desde]
    hace_un_anio = hoy - timedelta(days=365)
    ofertas = [
        o for o in ficha.get("ofertas_retencion_12m", []) if date.fromisoformat(o["fecha"]) > hace_un_anio
    ]
    return {
        "valor_mensual": _num(ficha.get("valor_mensual_total")),
        "antiguedad_meses": _num(ficha.get("antiguedad_meses")),
        "dias_mora": _num(ficha.get("dias_mora")),
        "tickets_90d": float(len(tickets)),
        "tickets_tecnicos_90d": float(sum(t.get("categoria") == "soporte_tecnico" for t in tickets)),
        "caidas_servicio_90d": None,
        "uso_datos_gb_mes": None,
        "nps_ultimo": None,
        "ofertas_retencion_12m": 1.0 if ofertas else 0.0,
        "tipo_servicio": tipo,
        "metodo_pago": None,
    }


def _num(valor: Any) -> float | None:
    try:
        return None if valor is None else float(valor)
    except (TypeError, ValueError):
        return None


ETIQUETAS = {
    "dias_mora": "días de mora",
    "tickets_90d": "tickets en 90 días",
    "tickets_tecnicos_90d": "tickets técnicos en 90 días",
    "antiguedad_meses": "antigüedad",
    "valor_mensual": "valor mensual",
    "ofertas_retencion_12m": "oferta previa",
    "nps_ultimo": "NPS",
    "caidas_servicio_90d": "caídas de red",
    "uso_datos_gb_mes": "uso de datos",
}


def factores(modelo: Any, fila: Any, top: int = 3) -> list[dict[str, Any]]:
    """Contribución de cada variable (coeficiente × valor transformado) en la regresión logística: qué empuja
    el riesgo hacia arriba en ESTE cliente. Vacío si el modelo no es lineal."""
    clf = modelo.named_steps.get("clf")
    if clf is None or not hasattr(clf, "coef_"):
        return []
    pre = modelo.named_steps["pre"]
    x = pre.transform(fila)
    x = x.toarray()[0] if hasattr(x, "toarray") else x[0]
    contribuciones = []
    for nombre, valor in zip(pre.get_feature_names_out(), clf.coef_[0] * x, strict=True):
        if valor <= 0 or nombre.startswith("num__missingindicator"):
            continue
        base = nombre.split("__", 1)[1]
        etiqueta = ETIQUETAS.get(base) or base.replace("_", " ")
        contribuciones.append({"variable": base, "descripcion": etiqueta, "aporte": round(float(valor), 3)})
    return sorted(contribuciones, key=lambda c: -c["aporte"])[:top]
