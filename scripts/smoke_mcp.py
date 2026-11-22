"""Prueba de humo del servidor MCP por protocolo (HTTP streamable), como lo usará el agente.

Requiere los contenedores arriba y el cliente FastMCP (usa el venv de apps/mcp-server):
    docker compose up -d mcp-server
    apps/mcp-server/.venv/Scripts/python scripts/smoke_mcp.py        # Windows
    uv run --project apps/mcp-server python scripts/smoke_mcp.py      # con uv

Verifica: catálogo de tools, PII filtrada, casos del golden (GQ-25 a GQ-28), confirmación firmada
(propuesta → token → ejecución; token falso, reusado o de otros parámetros rechazado), supervisor para
ajustes > $50.000 y el circuit breaker con el CRM caído. Los tokens se emiten con la CLI dentro del
contenedor (que tiene el secreto), igual que lo hará la API. Al terminar reinicia los mocks.
Salida: 0 todo OK · 1 alguna verificación falló · 2 servicios no disponibles.
"""

import asyncio
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any

from fastmcp import Client

ROOT = Path(__file__).resolve().parents[1]
MCP_URL = os.getenv("MCP_URL", "http://127.0.0.1:8090/mcp")
CONTENEDOR = os.getenv("MCP_CONTENEDOR", "claro-copiloto-mcp-server-1")
MOCKS = {"crm": "http://127.0.0.1:8081", "facturacion": "http://127.0.0.1:8082"}
PII = ("numero_documento", "celular", "email")


def api_key() -> str:
    if os.getenv("MOCKS_API_KEY"):
        return os.environ["MOCKS_API_KEY"]
    for linea in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if linea.strip().startswith("MOCKS_API_KEY="):
            return linea.split("=", 1)[1].strip().strip("'\"")
    return ""


def mock_admin(base: str, metodo: str, ruta: str, cuerpo: dict | None = None) -> None:
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    req = urllib.request.Request(  # noqa: S310 - URL local
        base + ruta,
        data=datos,
        method=metodo,
        headers={"X-API-Key": api_key(), "Content-Type": "application/json"},
    )
    urllib.request.urlopen(req, timeout=5).close()  # noqa: S310 # nosec B310


def emitir_token(accion: str, parametros: dict, asesor: str, rol: str = "asesor") -> str:
    """Simula a la API: el asesor confirmó en la UI y se firma el token (dentro del contenedor)."""
    cmd = [
        "docker",
        "exec",
        CONTENEDOR,
        "python",
        "-m",
        "copiloto_mcp.confirmacion",
        "--accion",
        accion,
        "--asesor",
        asesor,
        "--rol",
        rol,
        "--parametros",
        json.dumps(parametros, ensure_ascii=False),
    ]
    return subprocess.run(cmd, capture_output=True, text=True, check=True, encoding="utf-8").stdout.strip()  # noqa: S603


class Smoke:
    def __init__(self, cliente: Client):
        self.c = cliente
        self.ok, self.fallas = 0, []

    def check(self, cond: bool, desc: str, detalle: str = "") -> None:
        if cond:
            self.ok += 1
            print(f"  OK     {desc}")
        else:
            self.fallas.append(desc)
            print(f"  FALLA  {desc}" + (f"  -> {detalle[:300]}" if detalle else ""))

    async def tool(self, nombre: str, **args: Any) -> tuple[Any, str]:
        r = await self.c.call_tool(nombre, args, raise_on_error=False)
        texto = " ".join(getattr(b, "text", "") for b in r.content)
        return (None if r.is_error else r.data), texto

    async def correr(self) -> None:
        print("\n== Catálogo ==")
        tools = {t.name: t for t in await self.c.list_tools()}
        self.check(len(tools) == 11, f"{len(tools)} tools publicadas")
        escritura = [n for n, t in tools.items() if not t.annotations.read_only_hint]
        self.check(
            sorted(escritura) == ["aplicarAjuste", "crearTicket", "registrarOfertaRetencion"],
            f"escritura marcada: {sorted(escritura)}",
        )

        print("\n== Lectura y PII (GQ-25) ==")
        ficha, _ = await self.tool("obtenerCliente", cliente_id="C-1001")
        saldo, _ = await self.tool("obtenerSaldo", cliente_id="C-1001")
        self.check(
            ficha is not None and not any(k in ficha for k in PII),
            "ficha C-1001 sin documento, celular ni correo",
        )
        self.check(
            {s["plan"] for s in ficha["servicios"]} == {"Hogar Fibra 500", "Claro Max 60 GB"},
            "planes de C-1001",
        )
        self.check(
            saldo["saldo_pendiente"] == 169_315 and saldo["proxima_fecha_limite"] == "2026-11-25",
            "saldo $169.315, límite 2026-11-25",
        )

        print("\n== Retención (GQ-26, GQ-27) ==")
        r, _ = await self.tool("evaluarRetencion", cliente_id="C-1004")
        o = {x["codigo"]: x for x in r["servicios"][0]["ofertas"]}
        self.check(r["elegible"] and r["antiguedad_meses"] == 30, "C-1004 elegible con 30 meses")
        self.check(
            o["RET-A"]["porcentaje"] == 30 and o["RET-B"]["plan_destino"] == "Hogar Fibra 500",
            "C-1004: 30 % x 6 meses o upgrade a Hogar Fibra 500",
        )
        r, _ = await self.tool("evaluarRetencion", cliente_id="C-1007")
        self.check(
            not r["elegible"] and "45 días" in r["motivos_no_elegible"][0]["detalle"],
            "C-1007 no elegible (45 días de mora)",
        )
        _, err = await self.tool("registrarOfertaRetencion", cliente_id="C-1007", codigo="RET-A")
        self.check(err.startswith("CLIENTE_NO_ELEGIBLE"), "ni siquiera se propone oferta a C-1007")

        print("\n== Confirmación firmada (GQ-28) ==")
        r, _ = await self.tool("evaluarRetencion", cliente_id="C-1013")
        self.check(
            r["visita_tecnica_prioritaria"]["requerida"], "C-1013: 4 tickets técnicos → visita prioritaria"
        )
        args = {
            "cliente_id": "C-1013",
            "categoria": "soporte_tecnico",
            "descripcion": "Visita técnica prioritaria 24 h",
            "prioridad": "prioritaria",
            "escalar_a": "nivel2",
        }
        prop, _ = await self.tool("crearTicket", **args)
        self.check(prop["estado"] == "requiere_confirmacion", "sin token: solo propuesta, no ejecuta")
        falso = "token.inventado-por-el-llm"  # noqa: S105 - token falso a propósito
        _, err = await self.tool("crearTicket", **args, token_confirmacion=falso)
        self.check(err.startswith("CONFIRMACION_INVALIDA"), "token inventado → rechazado")
        token = emitir_token("crearTicket", prop["parametros"], "A-001")
        _, err = await self.tool(
            "crearTicket", **{**args, "escalar_a": "supervisor"}, token_confirmacion=token
        )
        self.check(err.startswith("CONFIRMACION_NO_COINCIDE"), "token con parámetros cambiados → rechazado")
        hecho, _ = await self.tool("crearTicket", **args, token_confirmacion=token)
        self.check(
            hecho and hecho["estado"] == "ejecutada",
            f"token válido → ticket {hecho and hecho['resultado']['ticket_id']}",
        )
        _, err = await self.tool("crearTicket", **args, token_confirmacion=token)
        self.check(err.startswith("CONFIRMACION_YA_USADA"), "mismo token otra vez → rechazado")
        r, _ = await self.tool("evaluarRetencion", cliente_id="C-1013")
        self.check(
            {x["codigo"]: x for x in r["servicios"][0]["ofertas"]}["RET-A"]["disponible"],
            "con la visita agendada, el descuento queda disponible",
        )

        print("\n== Ajuste > $50.000 ==")
        aj = {"factura_id": "F-5003", "valor": 80_000, "motivo": "Cobro no reconocido"}
        prop, _ = await self.tool("aplicarAjuste", **aj)
        self.check(prop["requiere_rol"] == "supervisor", "propuesta exige supervisor")
        _, err = await self.tool(
            "aplicarAjuste",
            **aj,
            token_confirmacion=emitir_token("aplicarAjuste", prop["parametros"], "A-001"),
        )
        self.check(err.startswith("AJUSTE_REQUIERE_APROBACION"), "token de asesor → rechazado")
        hecho, _ = await self.tool(
            "aplicarAjuste",
            **aj,
            token_confirmacion=emitir_token("aplicarAjuste", prop["parametros"], "SUP-001", "supervisor"),
        )
        self.check(
            hecho and hecho["resultado"]["aprobado_por"] == "SUP-001",
            "token de supervisor → aplicado con aprobado_por",
        )

        print("\n== Circuit breaker (CRM caído) ==")
        mock_admin(MOCKS["crm"], "PUT", "/_admin/config", {"fail_rate": 1})
        errores = [(await self.tool("obtenerCliente", cliente_id="C-1001"))[1] for _ in range(3)]
        self.check("SERVICIO_NO_DISPONIBLE" in errores[0], "CRM 503 tras reintentos → error claro al agente")
        self.check(errores[-1].startswith("CIRCUITO_ABIERTO"), f"luego falla rápido: {errores[-1][:70]}")
        with urllib.request.urlopen(MCP_URL.removesuffix("/mcp") + "/health", timeout=3) as h:  # noqa: S310 # nosec B310
            estado = json.loads(h.read())["sistemas"]["crm"]
        self.check(
            estado["estado"] == "abierto",
            f"/health: crm {estado['estado']}, reintentos {estado['reintentos']}",
        )
        saldo, _ = await self.tool("obtenerSaldo", cliente_id="C-1001")
        self.check(saldo is not None, "Facturación sigue operando (circuito independiente)")


async def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if not api_key():
        print("Defina MOCKS_API_KEY en el entorno o en .env")
        return 2
    try:
        async with Client(MCP_URL) as cliente:
            smoke = Smoke(cliente)
            for base in MOCKS.values():
                mock_admin(base, "POST", "/_admin/reset")
            try:
                await smoke.correr()
            finally:
                for base in MOCKS.values():
                    mock_admin(
                        base,
                        "PUT",
                        "/_admin/config",
                        {"fail_rate": float(os.getenv("MOCKS_FAIL_RATE", "0.02"))},
                    )
                    mock_admin(base, "POST", "/_admin/reset")
                print(
                    "\nMocks restaurados y datos reiniciados. El circuito del CRM se cierra solo en ≤ 30 s."
                )
    except (OSError, RuntimeError) as e:
        print(f"MCP o mocks no disponibles ({e}). ¿docker compose up -d mcp-server?")
        return 2
    print(f"\nRESULTADO: {smoke.ok}/{smoke.ok + len(smoke.fallas)} OK")
    for f in smoke.fallas:
        print(f"  - {f}")
    return 0 if not smoke.fallas else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
