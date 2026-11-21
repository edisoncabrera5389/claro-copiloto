"""POL-RET-2026 v3.1 regla por regla (función pura, datos sintéticos)."""

import pytest

from copiloto_mcp.retencion import evaluar_retencion, siguiente_plan, tramo

from .datos import HOY, factura, ficha, servicio, ticket


def evaluar(f, tickets=(), facturas=None, **kw):
    return evaluar_retencion(f, list(tickets), HOY, facturas, **kw)


def ofertas(r, i=0):
    return {o["codigo"]: o for o in r["servicios"][i]["ofertas"]}


@pytest.mark.parametrize(
    ("meses", "esperado"), [(25, "mas_de_24"), (24, "12_a_24"), (12, "12_a_24"), (11, "menos_de_12")]
)
def test_tramos_de_la_matriz(meses, esperado):
    assert tramo(meses) == esperado


def test_mas_de_24_meses_descuento_30_y_upgrade_al_siguiente_plan():
    r = evaluar(ficha(servicios=[servicio("hogar", "Hogar Fibra 300", 89_900, 30)]))
    assert r["elegible"] and r["antiguedad_meses"] == 30 and r["tramo"] == "mas_de_24"
    o = ofertas(r)
    assert o["RET-A"]["porcentaje"] == 30 and o["RET-A"]["meses"] == 6
    assert o["RET-A"]["valor_descuento_mensual"] == 26_970 and o["RET-A"]["valor_con_descuento"] == 62_930
    assert o["RET-B"]["plan_destino"] == "Hogar Fibra 500" and o["RET-B"]["meses"] == 6
    assert all(x["disponible"] for x in o.values())
    assert r["politica"] == "POL-RET-2026 v3.1"


def test_entre_12_y_24_descuento_20_y_upgrade_de_datos():
    r = evaluar(ficha(servicios=[servicio("movil", "Claro Max 25 GB", 49_900, 18)]))
    o = ofertas(r)
    assert r["tramo"] == "12_a_24"
    assert (o["RET-A"]["porcentaje"], o["RET-A"]["meses"]) == (20, 3)
    assert o["RET-B"]["plan_destino"] == "Claro Max 60 GB" and "datos" in o["RET-B"]["descripcion"]


@pytest.mark.parametrize(
    ("tipo", "plan", "codigo", "texto"),
    [("hogar", "Hogar Fibra 300", "RET-A", "repetidor"), ("movil", "Claro Max 25 GB", "RET-B", "10 GB")],
)
def test_menos_de_12_meses_beneficio_segun_tipo(tipo, plan, codigo, texto):
    r = evaluar(ficha(servicios=[servicio(tipo, plan, 50_000, 8)]))
    o = ofertas(r)
    assert list(o) == [codigo] and texto in o[codigo]["descripcion"] and o[codigo]["tipo"] == "beneficio"


def test_mora_mayor_a_30_no_es_elegible():
    r = evaluar(ficha(mora=45))
    assert not r["elegible"] and r["motivos_no_elegible"][0]["codigo"] == "MORA_MAYOR_30_DIAS"
    assert r["servicios"][0]["ofertas"] == []
    assert "sin prometer descuentos" in r["siguientes_pasos"][0]


def test_mora_de_30_si_es_elegible():
    assert evaluar(ficha(mora=30))["elegible"]


@pytest.mark.parametrize(
    ("fecha", "elegible"), [("2026-01-10", False), ("2025-11-18", True), ("2025-06-01", True)]
)
def test_una_oferta_cada_12_meses(fecha, elegible):
    r = evaluar(ficha(ofertas=[{"codigo": "RET-A", "descripcion": "x", "fecha": fecha}]))
    assert r["elegible"] is elegible


def test_cliente_retirado():
    assert evaluar(ficha(estado="retirado"))["motivos_no_elegible"][0]["codigo"] == "CLIENTE_RETIRADO"


def test_antiguedad_usa_el_servicio_mas_antiguo_activo():
    f = ficha(
        servicios=[
            servicio("hogar", "Hogar Fibra 300", 89_900, 10, sid="S1"),
            servicio("movil", "Claro Max 60 GB", 59_415, 30, sid="S2"),
            servicio("movil", "Claro Max 25 GB", 49_900, 80, sid="S3", estado="retirado"),
        ]
    )
    r = evaluar(f)
    assert r["antiguedad_meses"] == 30 and len(r["servicios"]) == 2


def test_tres_tickets_tecnicos_exigen_visita_antes_del_descuento():
    tk = [ticket(5), ticket(30), ticket(80), ticket(100), ticket(10, "facturacion")]
    r = evaluar(ficha(), tk)
    v = r["visita_tecnica_prioritaria"]
    assert v["requerida"] and not v["agendada"] and v["tickets_tecnicos_90d"] == 3 and v["plazo_horas"] == 24
    o = ofertas(r)
    assert not o["RET-A"]["disponible"] and "visita técnica prioritaria" in o["RET-A"]["restriccion"]
    assert o["RET-B"]["disponible"]  # el upgrade no es descuento
    assert "crearTicket" in r["siguientes_pasos"][0]


def test_con_visita_prioritaria_abierta_el_descuento_queda_disponible():
    tk = [ticket(5), ticket(30), ticket(0, prioridad="prioritaria", estado="abierto")]
    r = evaluar(ficha(), tk)
    assert r["visita_tecnica_prioritaria"]["agendada"] and ofertas(r)["RET-A"]["disponible"]


def test_dos_tickets_tecnicos_no_exigen_visita():
    assert not evaluar(ficha(), [ticket(5), ticket(6)])["visita_tecnica_prioritaria"]["requerida"]


@pytest.mark.parametrize(("valor", "aplica"), [(150_000, True), (149_999, False)])
def test_mesa_especializada_desde_150000(valor, aplica):
    r = evaluar(ficha(servicios=[servicio("hogar", "Hogar Fibra 900", valor, 30)]))
    assert r["mesa_especializada"]["aplica"] is aplica
    assert any("Mesa de Retención" in p for p in r["siguientes_pasos"]) is aplica


def test_promo_fibra500_por_servicio_nuevo_bloquea_descuento():
    r = evaluar(ficha(servicios=[servicio("hogar", "Hogar Fibra 500", 109_900, 1)]))
    assert r["promo_fibra500_vigente"]
    # < 12 meses no tiene descuento: no hay bloqueo que aplicar
    assert ofertas(r)["RET-A"]["disponible"]


def test_promo_fibra500_en_factura_bloquea_descuento_y_no_el_upgrade():
    f = ficha(servicios=[servicio("hogar", "Hogar Fibra 500", 109_900, 30)])
    r = evaluar(f, facturas=[factura(["Cargo fijo Hogar Fibra 500", "Descuento Promoción Fibra 500"])])
    o = ofertas(r)
    assert r["promo_fibra500_vigente"]
    assert not o["RET-A"]["disponible"] and "Fibra 500" in o["RET-A"]["restriccion"]
    assert o["RET-B"]["disponible"] and o["RET-B"]["plan_destino"] == "Hogar Fibra 900"


def test_fibra500_antiguo_sin_promo():
    assert not evaluar(ficha(servicios=[servicio("hogar", "Hogar Fibra 500", 109_900, 40)]))[
        "promo_fibra500_vigente"
    ]


@pytest.mark.parametrize("plan", ["Triple Play 500", "Hogar Fibra 900"])
def test_sin_plan_superior_no_hay_upgrade(plan):
    o = ofertas(evaluar(ficha(servicios=[servicio("hogar", plan, 169_900, 30)])))
    assert not o["RET-B"]["disponible"] and "no tiene un plan superior" in o["RET-B"]["restriccion"]


def test_escalera_incluye_el_plan_30gb_del_catalogo_v2():
    assert siguiente_plan("movil", "Claro Max 30 GB") == "Claro Max 60 GB"
    assert siguiente_plan("movil", "Claro Max Ilimitado") is None
    assert siguiente_plan("hogar", "Plan inexistente") is None


def test_filtrar_por_servicio():
    f = ficha(
        servicios=[
            servicio("hogar", "Hogar Fibra 300", 89_900, 30, sid="S1"),
            servicio("movil", "Claro Max 60 GB", 59_415, 30, sid="S2"),
        ]
    )
    r = evaluar(f, servicio_id="S2")
    assert [s["servicio_id"] for s in r["servicios"]] == ["S2"]


def test_reglas_de_conducta_siempre_presentes():
    assert any("dos ofertas" in r for r in evaluar(ficha())["reglas_conducta"])
