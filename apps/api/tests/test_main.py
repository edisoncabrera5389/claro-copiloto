"""API: autenticación, chat (SSE y síncrono), confirmación de acciones por rol, feedback y límites."""

import json

import pytest
from fastapi.testclient import TestClient

from copiloto_api.llm import Respuesta
from copiloto_api.main import crear_app

from .fakes import PASSWORD, FakeLLM, FakeMCP, dependencias, llamada, settings


def cliente(d=None, **cambios):
    s = settings(**cambios)
    return TestClient(crear_app(s, d or dependencias(s=s)))


def token(c, usuario="A-001"):
    r = c.post("/auth/login", json={"usuario": usuario, "password": PASSWORD})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_login():
    with cliente() as c:
        assert c.post("/auth/login", json={"usuario": "A-001", "password": "mala"}).status_code == 401
        assert c.post("/auth/login", json={"usuario": "X-1", "password": PASSWORD}).status_code == 401
        r = c.post("/auth/login", json={"usuario": "SUP-001", "password": PASSWORD}).json()
        assert r["usuario"]["rol"] == "supervisor"


def test_chat_requiere_token_valido():
    with cliente() as c:
        assert c.post("/chat/sincrono", json={"mensaje": "hola"}).status_code == 401
        assert (
            c.post(
                "/chat/sincrono", json={"mensaje": "hola"}, headers={"Authorization": "Bearer x"}
            ).status_code
            == 401
        )


def test_chat_sincrono_audita_y_guarda_memoria():
    d = dependencias(FakeLLM([Respuesta("Cuesta $109.900 [1].", [])]))
    with cliente(d) as c:
        r = c.post(
            "/chat/sincrono", json={"mensaje": "¿Precio Fibra 500? CC 1023456789"}, headers=token(c)
        ).json()
        assert (
            r["respuesta"] == "Cuesta $109.900 [1]."
            and r["fuentes"][0]["citada"]
            and r["fuentes"][0]["extracto"]
        )
        assert r["uso"]["llamadas"] == 2 and r["latencias"]["total_ms"] >= r["latencias"]["ttft_ms"] >= 0
        auditoria = d.memoria.db["auditoria"].find_one({"turno_id": r["turno_id"]})
        assert auditoria["usuario"] == "A-001" and auditoria["prompt_versions"]["sistema"]
        assert "1023456789" not in json.dumps(auditoria, default=str)  # se audita enmascarado
        hist = c.get(f"/conversaciones/{r['sesion_id']}", headers=token(c)).json()
        assert hist[0]["respuesta"] == r["respuesta"]


def test_chat_sse_emite_eventos_en_orden():
    d = dependencias(FakeLLM([Respuesta("Hola asesor [1].", [])]))
    with cliente(d) as c, c.stream("POST", "/chat", json={"mensaje": "planes"}, headers=token(c)) as r:
        eventos = [ln.split(":", 1)[1].strip() for ln in r.iter_lines() if ln.startswith("event:")]
    assert eventos[0] == "inicio" and "token" in eventos and eventos[-1] == "fin"
    assert eventos.index("fuentes") < eventos.index("fin")


def test_error_en_el_turno_llega_como_evento():
    d = dependencias()

    async def explota(*a, **k):
        raise RuntimeError("LLM caído")

    d.llm.chat = explota
    with cliente(d) as c, c.stream("POST", "/chat", json={"mensaje": "planes"}, headers=token(c)) as r:
        texto = "".join(r.iter_lines())
    assert "event: error" in texto and "No se pudo completar" in texto


def _proponer(c, d, mensaje="Abre un ticket para C-1001", **args):
    d.llm.guion = [
        llamada("crearTicket", cliente_id="C-1001", **args),
        Respuesta("Propuesta lista (CRM).", []),
    ]
    r = c.post("/chat/sincrono", json={"mensaje": mensaje}, headers=token(c)).json()
    return r["propuestas"][0]["propuesta_id"]


def test_confirmar_firma_el_token_y_el_mcp_lo_verifica():
    d = dependencias()
    with cliente(d) as c:
        pid = _proponer(c, d, categoria="facturacion")
        assert [p["propuesta_id"] for p in c.get("/acciones/pendientes", headers=token(c)).json()] == [pid]
        r = c.post(f"/acciones/{pid}/confirmar", headers=token(c))
        assert r.status_code == 200 and r.json()["resultado"] == {
            "estado": "ejecutada",
            "accion": "crearTicket",
            "confirmada_por": "A-001",
            "rol": "asesor",
            "resultado": {"ticket_id": "TK-900001"},
        }
        assert "token_confirmacion" in d.mcp.llamadas[-1][1]
        assert c.post(f"/acciones/{pid}/confirmar", headers=token(c)).status_code == 404  # una sola vez
        accion = d.memoria.db["acciones"].find_one({"propuesta_id": pid})
        assert accion["ok"] and accion["confirmada_por"] == "A-001"


def test_ajuste_mayor_a_50000_requiere_supervisor():
    d = dependencias()
    with cliente(d) as c:
        pid = _proponer(c, d, "Aplica ajuste de 80000 a C-1001", valor=80_000)
        r = c.post(f"/acciones/{pid}/confirmar", headers=token(c, "A-001"))
        assert r.status_code == 403 and "supervisor" in r.json()["detail"]
        assert pid in [
            p["propuesta_id"] for p in c.get("/acciones/pendientes", headers=token(c, "SUP-001")).json()
        ]
        r = c.post(f"/acciones/{pid}/confirmar", headers=token(c, "SUP-001"))
        assert r.json()["resultado"]["rol"] == "supervisor"


def test_otro_asesor_no_puede_confirmar_ni_ver_la_propuesta():
    d = dependencias()
    with cliente(d) as c:
        pid = _proponer(c, d)
        assert c.get("/acciones/pendientes", headers=token(c, "A-002")).json() == []
        assert c.post(f"/acciones/{pid}/confirmar", headers=token(c, "A-002")).status_code == 403


def test_falla_transitoria_del_sistema_devuelve_la_propuesta():
    d = dependencias()
    with cliente(d) as c:
        pid = _proponer(c, d)
        original = d.mcp.llamar

        async def caido(nombre, args):
            return False, None, "CIRCUITO_ABIERTO: crm no disponible (sistema=crm)"

        d.mcp.llamar = caido
        assert c.post(f"/acciones/{pid}/confirmar", headers=token(c)).status_code == 502
        d.mcp.llamar = original
        assert c.post(f"/acciones/{pid}/confirmar", headers=token(c)).status_code == 200


def test_rechazar_propuesta():
    d = dependencias()
    with cliente(d) as c:
        pid = _proponer(c, d)
        assert c.post(f"/acciones/{pid}/rechazar", headers=token(c)).json() == {"estado": "rechazada"}
        assert c.post(f"/acciones/{pid}/rechazar", headers=token(c)).status_code == 404


def test_feedback():
    d = dependencias(FakeLLM([Respuesta("Ok [1].", [])]))
    with cliente(d) as c:
        turno = c.post("/chat/sincrono", json={"mensaje": "planes"}, headers=token(c)).json()["turno_id"]
        assert c.post(
            "/feedback", json={"turno_id": turno, "valor": -1, "comentario": "incompleta"}, headers=token(c)
        ).json() == {"estado": "registrado"}
        assert (
            c.post("/feedback", json={"turno_id": "noexiste", "valor": 1}, headers=token(c)).status_code
            == 404
        )
        assert d.memoria.db["feedback"].count_documents({"valor": -1}) == 1


def test_limite_de_solicitudes_por_usuario():
    with cliente(rate_limit_por_min=2) as c:
        h = token(c)
        codigos = [
            c.post("/chat/sincrono", json={"mensaje": "planes"}, headers=h).status_code for _ in range(3)
        ]
        ficha = c.get("/clientes/C-1001/ficha", headers=h).status_code  # cupo propio: no lo agota el chat
    assert codigos == [200, 200, 429] and ficha == 200


@pytest.mark.parametrize("ruta", ["/health", "/health/vivo"])
def test_salud(ruta):
    with cliente() as c:
        r = c.get(ruta).json()
    assert r["estado"] == "ok"
    if ruta == "/health":
        assert r["componentes"] == {"reranker": "desactivado", "redis": "ok"} and r["prompts"]["sistema"]


def test_ficha_del_cliente_en_paralelo_y_validacion():
    mcp = FakeMCP(
        {
            "obtenerCliente": lambda a: (True, {"cliente_id": a["cliente_id"], "nombre": "Ana"}, None),
            "obtenerSaldo": lambda a: (True, {"saldo_pendiente": 1000}, None),
            "listarFacturas": lambda a: (False, None, "SERVICIO_NO_DISPONIBLE: 503"),
        }
    )
    with cliente(dependencias(mcp=mcp)) as c:
        r = c.get("/clientes/C-1001/ficha", headers=token(c)).json()
        assert r["cliente"]["nombre"] == "Ana" and r["saldo"]["saldo_pendiente"] == 1000
        assert r["facturas"] is None  # degradación parcial: el panel muestra lo que hay
        assert c.get("/clientes/1001/ficha", headers=token(c)).status_code == 422
        assert c.get("/clientes/C-1001/ficha").status_code == 401


def test_ficha_cliente_inexistente_404():
    mcp = FakeMCP({"obtenerCliente": lambda a: (False, None, "CLIENTE_NO_ENCONTRADO: no existe")})
    with cliente(dependencias(mcp=mcp)) as c:
        assert c.get("/clientes/C-9999/ficha", headers=token(c)).status_code == 404


def test_escalamiento_manual_llega_a_la_cola_del_supervisor():
    d = dependencias(FakeLLM([Respuesta("Revisa [1].", [])]))
    with cliente(d) as c:
        r = c.post("/chat/sincrono", json={"mensaje": "Datos de C-1001"}, headers=token(c)).json()
        e = c.post(
            "/escalamientos",
            json={"sesion_id": r["sesion_id"], "motivo": "Cliente molesto, CC 1023456789"},
            headers=token(c),
        ).json()
        assert c.get("/escalamientos", headers=token(c)).status_code == 403  # el asesor no ve la cola
        cola = c.get("/escalamientos", headers=token(c, "SUP-001")).json()
        assert cola[0]["cliente_id"] == "C-1001" and cola[0]["turno_id"] == r["turno_id"]
        assert "1023456789" not in cola[0]["motivo"]  # Ley 1581
        ruta = f"/escalamientos/{e['escalamiento_id']}/atender"
        assert c.post(ruta, headers=token(c, "SUP-001")).json() == {"estado": "atendido"}
        assert c.post(ruta, headers=token(c, "SUP-001")).status_code == 404
        assert c.get("/escalamientos", headers=token(c, "SUP-001")).json() == []
