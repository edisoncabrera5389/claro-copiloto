"""Skill evaluarRetencion: Política de Retención de Clientes POL-RET-2026 v3.1, en código determinístico.

El LLM no decide la elegibilidad ni inventa ofertas: redacta a partir de este resultado.

Reglas (numerales de la política):
2. No elegible con mora > 30 días o con una oferta en los últimos 12 meses. Antigüedad = servicio
   más antiguo activo. Se calcula como round(días / 30,4375), igual que el campo del CRM.
3. Matriz: > 24 meses → RET-A 30 % × 6 / RET-B upgrade al siguiente plan × 6.
           12–24       → RET-A 20 % × 3 / RET-B upgrade de velocidad (hogar) o datos (móvil) × 3.
           < 12        → Hogar: repetidor WiFi gratis × 6 (columna A) / Móvil: 10 GB × 3 (columna B).
   Los descuentos no son acumulables con la Promoción Fibra 500.
4. ≥ 3 tickets de soporte técnico en 90 días → visita técnica prioritaria (24 h) ANTES de un descuento.
   Valor mensual ≥ $150.000 → puede transferirse a la Mesa de Retención Especializada.
5. Prohibido ofrecer beneficios no listados; si rechaza dos ofertas, tramitar la cancelación.
"""

import json
from datetime import date, timedelta
from functools import lru_cache
from importlib import resources
from typing import Any

POLITICA = "POL-RET-2026 v3.1"
MORA_MAXIMA_DIAS = 30
TICKETS_TECNICOS_VISITA = 3
VENTANA_TICKETS_DIAS = 90
UMBRAL_ALTO_VALOR = 150_000
DIAS_POR_MES = 30.4375
DURACION_PROMO_FIBRA500_DIAS = 92  # 3 meses de la promoción para clientes nuevos

REGLAS_CONDUCTA = [
    "No ofrecer descuentos ni beneficios distintos a los listados en la política.",
    "Si el cliente rechaza dos ofertas, tramitar la cancelación sin insistir.",
    "En portabilidad saliente, presentar la oferta una sola vez sin demorar el proceso.",
    "Registrar la oferta aceptada en el CRM con el código RET-A o RET-B.",
]


@lru_cache(maxsize=1)
def escalera_planes() -> dict[str, list[list[str]]]:
    datos = json.loads(resources.files("copiloto_mcp").joinpath("escalera_planes.json").read_text("utf-8"))
    return {"hogar": datos["hogar"], "movil": datos["movil"]}


def siguiente_plan(tipo: str, plan: str) -> str | None:
    niveles = escalera_planes().get(tipo, [])
    for i, nivel in enumerate(niveles):
        if plan in nivel:
            return niveles[i + 1][0] if i + 1 < len(niveles) else None
    return None


def _pesos(valor: int) -> str:
    return "$" + f"{valor:,}".replace(",", ".")


def _fecha(texto: str) -> date:
    return date.fromisoformat(texto)


def antiguedad_meses(servicios: list[dict[str, Any]], hoy: date) -> tuple[int, str | None]:
    activos = [s for s in servicios if s.get("estado") == "activo"]
    if not activos:
        return 0, None
    desde = min(_fecha(s["fecha_activacion"]) for s in activos)
    return round((hoy - desde).days / DIAS_POR_MES), desde.isoformat()


def tramo(meses: int) -> str:
    if meses > 24:
        return "mas_de_24"
    return "12_a_24" if meses >= 12 else "menos_de_12"


def promo_fibra500_vigente(
    servicios: list[dict[str, Any]], facturas: list[dict[str, Any]] | None, hoy: date
) -> bool:
    """Sin marca en el CRM: se infiere por un Hogar Fibra 500 nuevo o por el concepto en la factura."""
    limite = hoy - timedelta(days=DURACION_PROMO_FIBRA500_DIAS)
    nuevo_fibra500 = any(
        s.get("estado") == "activo" and "Fibra 500" in s["plan"] and _fecha(s["fecha_activacion"]) > limite
        for s in servicios
    )
    en_factura = any(
        "promo" in d["concepto"].lower() and "fibra 500" in d["concepto"].lower()
        for f in facturas or []
        for d in f.get("detalle", [])
    )
    return nuevo_fibra500 or en_factura


def _ofertas_servicio(
    servicio: dict[str, Any], tramo_cliente: str, promo: bool, visita_pendiente: bool
) -> list[dict[str, Any]]:
    tipo, plan, valor = servicio["tipo"], servicio["plan"], servicio["valor_mensual"]
    ofertas: list[dict[str, Any]] = []

    if tramo_cliente == "menos_de_12":
        if tipo == "hogar":
            ofertas.append(
                {
                    "codigo": "RET-A",
                    "tipo": "beneficio",
                    "meses": 6,
                    "descripcion": "Un repetidor WiFi gratis por 6 meses",
                }
            )
        else:
            ofertas.append(
                {
                    "codigo": "RET-B",
                    "tipo": "beneficio",
                    "meses": 3,
                    "descripcion": "10 GB adicionales por 3 meses",
                }
            )
    else:
        porcentaje, meses = (30, 6) if tramo_cliente == "mas_de_24" else (20, 3)
        descuento = round(valor * porcentaje / 100)
        ofertas.append(
            {
                "codigo": "RET-A",
                "tipo": "descuento",
                "porcentaje": porcentaje,
                "meses": meses,
                "valor_descuento_mensual": descuento,
                "valor_con_descuento": valor - descuento,
                "descripcion": f"{porcentaje} % de descuento en el cargo fijo de {plan} ({_pesos(valor)}) "
                f"por {meses} meses: {_pesos(descuento)} menos al mes",
            }
        )
        destino = siguiente_plan(tipo, plan)
        mejora = (
            "Upgrade al siguiente plan"
            if tramo_cliente == "mas_de_24"
            else ("Upgrade de velocidad" if tipo == "hogar" else "Upgrade de datos")
        )
        ofertas.append(
            {
                "codigo": "RET-B",
                "tipo": "upgrade",
                "meses": meses,
                "plan_destino": destino,
                "descripcion": f"{mejora}: {plan} → {destino} sin costo adicional por {meses} meses"
                if destino
                else f"{mejora} sin costo por {meses} meses",
            }
        )

    for o in ofertas:
        o["disponible"], o["restriccion"] = True, None
        if o["codigo"] == "RET-B" and o["tipo"] == "upgrade" and not o["plan_destino"]:
            o["disponible"], o["restriccion"] = (
                False,
                f"{plan} no tiene un plan superior en el catálogo vigente",
            )
        if o["tipo"] == "descuento" and promo:
            o["disponible"], o["restriccion"] = (
                False,
                "Los descuentos de retención no son acumulables con la Promoción Fibra 500",
            )
        elif o["tipo"] == "descuento" and visita_pendiente:
            o["disponible"] = False
            o["restriccion"] = (
                "Primero se debe agendar la visita técnica prioritaria (24 h); "
                "luego se puede ofrecer el descuento"
            )
    return ofertas


def evaluar_retencion(
    ficha: dict[str, Any],
    tickets: list[dict[str, Any]],
    hoy: date,
    facturas: list[dict[str, Any]] | None = None,
    servicio_id: str | None = None,
) -> dict[str, Any]:
    """`tickets`: los de la ventana de 90 días.
    `facturas`: las recientes, o None si Facturación no respondió."""
    servicios = [s for s in ficha["servicios"] if s.get("estado") == "activo"]
    if servicio_id:
        servicios = [s for s in servicios if s["servicio_id"] == servicio_id]
    meses, desde = antiguedad_meses(ficha["servicios"], hoy)
    tramo_cliente = tramo(meses)

    motivos: list[dict[str, str]] = []
    if ficha.get("estado") == "retirado":
        motivos.append({"codigo": "CLIENTE_RETIRADO", "detalle": "El cliente está retirado"})
    if ficha["dias_mora"] > MORA_MAXIMA_DIAS:
        motivos.append(
            {
                "codigo": "MORA_MAYOR_30_DIAS",
                "detalle": f"Tiene {ficha['dias_mora']} días de mora (máximo {MORA_MAXIMA_DIAS})",
            }
        )
    hace_un_anio = (
        hoy - timedelta(days=365) if (hoy.month, hoy.day) == (2, 29) else hoy.replace(year=hoy.year - 1)
    )
    previas = [o for o in ficha.get("ofertas_retencion_12m", []) if _fecha(o["fecha"]) > hace_un_anio]
    if previas:
        motivos.append(
            {
                "codigo": "OFERTA_ULTIMOS_12_MESES",
                "detalle": f"Ya recibió la oferta {previas[0]['codigo']} el {previas[0]['fecha']}",
            }
        )
    elegible = not motivos

    desde_90 = hoy - timedelta(days=VENTANA_TICKETS_DIAS)
    tecnicos = [t for t in tickets if t["categoria"] == "soporte_tecnico" and _fecha(t["fecha"]) >= desde_90]
    visita_agendada = any(
        t.get("prioridad") == "prioritaria" and t.get("estado") == "abierto" for t in tecnicos
    )
    requiere_visita = len(tecnicos) >= TICKETS_TECNICOS_VISITA
    visita_pendiente = requiere_visita and not visita_agendada
    promo = promo_fibra500_vigente(ficha["servicios"], facturas, hoy)
    alto_valor = ficha["valor_mensual_total"] >= UMBRAL_ALTO_VALOR

    resultado_servicios = [
        {
            "servicio_id": s["servicio_id"],
            "tipo": s["tipo"],
            "plan": s["plan"],
            "valor_mensual": s["valor_mensual"],
            "ofertas": _ofertas_servicio(s, tramo_cliente, promo, visita_pendiente) if elegible else [],
        }
        for s in servicios
    ]

    pasos: list[str] = []
    if not elegible:
        pasos.append(
            "Informar al cliente que no aplica oferta de retención, sin prometer descuentos, "
            "y tramitar su solicitud."
        )
    else:
        if visita_pendiente:
            pasos.append(
                "Agendar visita técnica prioritaria en 24 h con crearTicket (categoria=soporte_tecnico, "
                "prioridad=prioritaria, escalar_a=nivel2) antes de ofrecer descuentos."
            )
        pasos.append(
            "Presentar las ofertas disponibles; registrar la aceptada con registrarOfertaRetencion "
            "(requiere confirmación)."
        )
        if alto_valor:
            pasos.append(
                "Cliente de alto valor: puede transferirse a la Mesa de Retención Especializada "
                "(crearTicket con escalar_a=mesa_retencion)."
            )

    return {
        "cliente_id": ficha["cliente_id"],
        "politica": POLITICA,
        "fecha_evaluacion": hoy.isoformat(),
        "elegible": elegible,
        "motivos_no_elegible": motivos,
        "antiguedad_meses": meses,
        "antiguedad_desde": desde,
        "tramo": tramo_cliente,
        "dias_mora": ficha["dias_mora"],
        "visita_tecnica_prioritaria": {
            "requerida": requiere_visita,
            "agendada": visita_agendada,
            "tickets_tecnicos_90d": len(tecnicos),
            "umbral": TICKETS_TECNICOS_VISITA,
            "plazo_horas": 24,
        },
        "mesa_especializada": {
            "aplica": alto_valor,
            "valor_mensual_total": ficha["valor_mensual_total"],
            "umbral": UMBRAL_ALTO_VALOR,
        },
        "promo_fibra500_vigente": promo,
        "servicios": resultado_servicios,
        "siguientes_pasos": pasos,
        "reglas_conducta": REGLAS_CONDUCTA,
    }
