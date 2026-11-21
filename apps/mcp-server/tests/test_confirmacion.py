import pytest

from copiloto_mcp import confirmacion
from copiloto_mcp.confirmacion import Confirmaciones, ConfirmacionInvalida, huella

from .conftest import SECRETO

PARAMS = {"cliente_id": "C-1004", "codigo": "RET-A", "descripcion": "30 %"}


def nuevo(t: list[float] | None = None) -> Confirmaciones:
    t = t if t is not None else [1_000.0]
    return Confirmaciones(SECRETO, ttl_s=300, reloj=lambda: t[0])


def codigo_de(fn) -> str:
    with pytest.raises(ConfirmacionInvalida) as e:
        fn()
    return e.value.codigo


def test_emitir_y_verificar():
    c = nuevo()
    tok = c.emitir("registrarOfertaRetencion", PARAMS, "A-001")
    v = c.verificar(tok, "registrarOfertaRetencion", dict(reversed(list(PARAMS.items()))))  # orden no importa
    assert (v.asesor_id, v.rol, v.accion) == ("A-001", "asesor", "registrarOfertaRetencion")


def test_huella_estable_e_independiente_del_orden():
    assert huella("a", {"x": 1, "y": "ñ"}) == huella("a", {"y": "ñ", "x": 1})
    assert huella("a", {"x": 1}) != huella("b", {"x": 1})


def test_firma_alterada_o_secreto_distinto():
    c = nuevo()
    tok = c.emitir("crearTicket", PARAMS, "A-001")
    cuerpo, firma = tok.split(".")
    assert (
        codigo_de(lambda: c.verificar(f"{cuerpo}.{firma[:-2]}xx", "crearTicket", PARAMS))
        == "CONFIRMACION_INVALIDA"
    )
    otro = Confirmaciones("otro-secreto-distinto-con-mas-de-32-chars", 300)
    assert codigo_de(lambda: otro.verificar(tok, "crearTicket", PARAMS)) == "CONFIRMACION_INVALIDA"
    assert codigo_de(lambda: c.verificar("basura", "crearTicket", PARAMS)) == "CONFIRMACION_INVALIDA"


def test_rol_supervisor_alterado_invalida_la_firma():
    import base64
    import json

    c = nuevo()
    cuerpo, firma = c.emitir("aplicarAjuste", PARAMS, "A-001").split(".")
    p = json.loads(base64.urlsafe_b64decode(cuerpo + "=" * (-len(cuerpo) % 4)))
    p["rol"] = "supervisor"
    falso = base64.urlsafe_b64encode(json.dumps(p).encode()).rstrip(b"=").decode()
    assert (
        codigo_de(lambda: c.verificar(f"{falso}.{firma}", "aplicarAjuste", PARAMS)) == "CONFIRMACION_INVALIDA"
    )


def test_expira():
    t = [1_000.0]
    c = nuevo(t)
    tok = c.emitir("crearTicket", PARAMS, "A-001")
    t[0] += 299
    c.verificar(tok, "crearTicket", PARAMS)
    t[0] += 1
    assert codigo_de(lambda: c.verificar(tok, "crearTicket", PARAMS)) == "CONFIRMACION_EXPIRADA"


def test_no_sirve_para_otros_parametros_ni_otra_accion():
    c = nuevo()
    tok = c.emitir("registrarOfertaRetencion", PARAMS, "A-001")
    assert codigo_de(lambda: c.verificar(tok, "registrarOfertaRetencion", {**PARAMS, "codigo": "RET-B"})) == (
        "CONFIRMACION_NO_COINCIDE"
    )
    assert codigo_de(lambda: c.verificar(tok, "crearTicket", PARAMS)) == "CONFIRMACION_NO_COINCIDE"


def test_uso_unico_y_liberacion():
    t = [1_000.0]
    c = nuevo(t)
    tok = c.emitir("crearTicket", PARAMS, "A-001")
    v = c.verificar(tok, "crearTicket", PARAMS)
    c.consumir(v)
    assert codigo_de(lambda: c.verificar(tok, "crearTicket", PARAMS)) == "CONFIRMACION_YA_USADA"
    c.liberar(v)
    c.verificar(tok, "crearTicket", PARAMS)
    c.consumir(v)
    t[0] += 301  # al expirar se purga de la lista de consumidos
    c._purgar()
    assert c._consumidos == {}


def test_rol_invalido_al_emitir():
    with pytest.raises(ValueError):
        nuevo().emitir("crearTicket", PARAMS, "A-001", rol="admin")


def test_cli_emite_token_valido(monkeypatch, capsys):
    monkeypatch.setenv("MCP_CONFIRMACION_SECRET", SECRETO)
    monkeypatch.setattr(
        "sys.argv",
        [
            "x",
            "--accion",
            "crearTicket",
            "--asesor",
            "A-9",
            "--rol",
            "supervisor",
            "--parametros",
            '{"a": 1}',
        ],
    )
    assert confirmacion.main() == 0
    tok = capsys.readouterr().out.strip()
    assert Confirmaciones(SECRETO).verificar(tok, "crearTicket", {"a": 1}).rol == "supervisor"


def test_cli_sin_secreto(monkeypatch):
    monkeypatch.delenv("MCP_CONFIRMACION_SECRET", raising=False)
    monkeypatch.setattr("sys.argv", ["x", "--accion", "crearTicket", "--asesor", "A", "--parametros", "{}"])
    assert confirmacion.main() == 2
