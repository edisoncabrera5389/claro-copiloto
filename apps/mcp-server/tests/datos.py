"""Datos sintéticos para las pruebas unitarias (no son los insumos de la prueba)."""

from datetime import date, timedelta
from typing import Any

HOY = date(2026, 11, 18)
DOC, CEL, MAIL = "1234567890", "300 123 4567", "sintetico@ejemplo.test"


def hace_meses(meses: float) -> str:
    return (HOY - timedelta(days=round(meses * 30.4375))).isoformat()


def servicio(tipo: str, plan: str, valor: int, meses: float, sid: str = "S1", estado: str = "activo") -> dict:
    return {
        "servicio_id": sid,
        "tipo": tipo,
        "plan": plan,
        "valor_mensual": valor,
        "fecha_activacion": hace_meses(meses),
        "permanencia_hasta": None,
        "estado": estado,
        "equipos": [],
    }


def ficha(
    cliente_id: str = "C-2001",
    servicios: list[dict] | None = None,
    mora: int = 0,
    ofertas: list[dict] | None = None,
    estado: str = "activo",
) -> dict[str, Any]:
    servicios = servicios if servicios is not None else [servicio("hogar", "Hogar Fibra 300", 89_900, 30)]
    return {
        "cliente_id": cliente_id,
        "nombre": "Cliente Sintético",
        "tipo_documento": "CC",
        "numero_documento": DOC,
        "celular": CEL,
        "email": MAIL,
        "ciudad": "Bogotá",
        "segmento": "masivo",
        "estado": estado,
        "dias_mora": mora,
        "valor_mensual_total": sum(s["valor_mensual"] for s in servicios if s["estado"] == "activo"),
        "servicios": servicios,
        "tickets_recientes": [],
        "ofertas_retencion_12m": ofertas or [],
        "autorizacion_tratamiento_datos": True,
    }


def ticket(dias_atras: int, categoria: str = "soporte_tecnico", **extra: Any) -> dict:
    return {
        "ticket_id": f"TK-{100000 + dias_atras}",
        "fecha": (HOY - timedelta(days=dias_atras)).isoformat(),
        "categoria": categoria,
        "estado": "cerrado",
        **extra,
    }


def factura(conceptos: list[str] | None = None) -> dict:
    return {
        "factura_id": "F-9001",
        "cliente_id": "C-2001",
        "periodo": "2026-11",
        "valor_total": 89_900,
        "detalle": [{"concepto": c, "valor": 1} for c in (conceptos or ["Cargo fijo Hogar Fibra 300"])],
        "estado": "pendiente",
    }
