"""Prueba de humo de los mocks levantados con docker compose (CRM 8081, Facturación 8082, ERP 8083).

Verifica autenticación, reglas de negocio (409/403), 429 con Retry-After, 503 simulado y que los logs
de los contenedores no contengan PII. Al terminar SIEMPRE restaura la configuración de .env y reinicia
los datos (se pierden tickets, ofertas y ajustes creados), para dejar los mocks limpios para la demo.

Solo usa la librería estándar:
    docker compose up -d crm-mock facturacion-mock erp-mock
    py -3.13 scripts/smoke_mocks.py                # usa MOCKS_API_KEY del entorno o de .env
    py -3.13 scripts/smoke_mocks.py --muestras-503 0 --sin-logs   # versión rápida

Código de salida: 0 si todo pasa, 1 si alguna verificación falla, 2 si los mocks no responden.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


class Respuesta:
    def __init__(self, status: int, headers: dict[str, str], cuerpo: bytes):
        self.status = status
        self.headers = {k.lower(): v for k, v in headers.items()}
        self.texto = cuerpo.decode("utf-8", errors="replace")

    def json(self) -> Any:
        return json.loads(self.texto) if self.texto else None

    def es_error(self, codigo: str) -> bool:
        try:
            j = self.json()
        except json.JSONDecodeError:
            return False
        return isinstance(j, dict) and set(j) >= {"codigo", "mensaje", "trace_id"} and j["codigo"] == codigo


class Smoke:
    def __init__(self, args: argparse.Namespace, api_key: str):
        self.crm, self.fac, self.erp = args.crm, args.facturacion, args.erp
        self.key = api_key
        self.ok = 0
        self.fallas: list[str] = []
        self.reintentos_503 = 0

    # --- HTTP ---------------------------------------------------------------------------------
    def http(
        self, metodo: str, url: str, cuerpo: Any = None, clave: str | None = "", headers: dict | None = None
    ) -> Respuesta:
        cab = {"Accept": "application/json", **(headers or {})}
        if clave is not None:
            cab["X-API-Key"] = clave or self.key
        datos = None
        if cuerpo is not None:
            datos = json.dumps(cuerpo).encode()
            cab["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=datos, headers=cab, method=metodo)  # noqa: S310
        try:
            with urllib.request.urlopen(req, timeout=5) as r:  # noqa: S310 - URL local configurable # nosec B310
                return Respuesta(r.status, dict(r.headers), r.read())
        except urllib.error.HTTPError as e:
            return Respuesta(e.code, dict(e.headers), e.read())

    def api(self, metodo: str, url: str, cuerpo: Any = None, **kw: Any) -> Respuesta:
        """Reintenta solo ante 503 (falla simulada), como hará el cliente MCP."""
        for _ in range(5):
            r = self.http(metodo, url, cuerpo, **kw)
            if r.status != 503:
                return r
            self.reintentos_503 += 1
        return r

    def admin(self, base: str, **cfg: Any) -> None:
        self.http("PUT", f"{base}/_admin/config", cfg)

    def reset(self, base: str) -> None:
        self.http("POST", f"{base}/_admin/reset")

    # --- Resultado ----------------------------------------------------------------------------
    def check(self, condicion: bool, descripcion: str, detalle: str = "") -> None:
        if condicion:
            self.ok += 1
            print(f"  OK     {descripcion}")
        else:
            self.fallas.append(descripcion)
            print(f"  FALLA  {descripcion}" + (f"  -> {detalle[:300]}" if detalle else ""))

    # --- Secciones ----------------------------------------------------------------------------
    def transversal(self) -> None:
        print("\n== Transversal ==")
        rutas = {
            "crm": (self.crm, "/v1/clientes/C-1001"),
            "facturacion": (self.fac, "/v1/facturas/F-5001"),
            "erp": (self.erp, "/v1/ordenes-servicio?cliente_id=C-1001"),
        }
        for nombre, (base, ruta) in rutas.items():
            r = self.http("GET", f"{base}/health", clave=None)
            self.check(
                r.status == 200 and r.json() == {"estado": "ok", "servicio": nombre}, f"{nombre}: /health"
            )
            r = self.http("GET", base + ruta, clave=None)
            self.check(
                r.status == 401 and r.es_error("NO_AUTORIZADO"), f"{nombre}: sin API key -> 401", r.texto
            )
            r = self.http("GET", base + ruta, clave="clave-incorrecta")
            self.check(r.status == 401, f"{nombre}: API key incorrecta -> 401")
            self.check(self.http("GET", f"{base}/docs", clave=None).status == 200, f"{nombre}: /docs")
        trace = "4bf92f3577b34da6a3ce929d0e0e4736"
        r = self.api(
            "GET",
            f"{self.crm}/v1/clientes/C-9999",
            headers={"traceparent": f"00-{trace}-00f067aa0ba902b7-01"},
        )
        self.check(r.headers.get("x-trace-id") == trace, "traceparent W3C se propaga a X-Trace-Id")

    def crm_casos(self) -> dict[str, Any]:
        print("\n== CRM ==")
        c = self.crm
        ficha = self.api("GET", f"{c}/v1/clientes/C-1004").json()
        r = self.api(
            "GET",
            f"{c}/v1/clientes?tipo_documento={ficha['tipo_documento']}&numero_documento={ficha['numero_documento']}",
        )
        self.check(
            r.status == 200 and set(r.json()) == {"cliente_id", "nombre", "estado"},
            "buscar por documento -> resumen sin PII",
            r.texto,
        )
        self.check(self.api("GET", f"{c}/v1/clientes/C-12").status == 400, "id fuera de ^C-\\d{4}$ -> 400")
        self.check(self.api("GET", f"{c}/v1/clientes/C-9999").status == 404, "cliente inexistente -> 404")
        srv = self.api("GET", f"{c}/v1/clientes/C-1001/servicios").json()
        self.check(isinstance(srv, list) and len(srv) == 2, "C-1001: 2 servicios activos")
        tk = self.api("GET", f"{c}/v1/clientes/C-1013/tickets").json()
        self.check(
            len(tk) == 4 and all(t["categoria"] == "soporte_tecnico" for t in tk),
            "C-1013: 4 tickets técnicos en 90 días (visita prioritaria)",
        )
        self.check(
            self.api("GET", f"{c}/v1/clientes/C-1013/tickets?dias=366").status == 400, "dias=366 -> 400"
        )
        r = self.api(
            "POST",
            f"{c}/v1/clientes/C-1013/tickets",
            {"categoria": "soporte_tecnico", "descripcion": "Visita prioritaria", "prioridad": "prioritaria"},
        )
        self.check(r.status == 201 and r.json().get("estado") == "abierto", "crear ticket -> 201", r.texto)
        oferta = {"codigo": "RET-A", "descripcion": "30 % x 6 meses", "asesor_id": "A-001"}
        r = self.api("POST", f"{c}/v1/clientes/C-1004/ofertas-retencion", oferta)
        self.check(r.status == 201, "C-1004: oferta RET-A -> 201 (caso GQ-26)", r.texto)
        r = self.api("POST", f"{c}/v1/clientes/C-1004/ofertas-retencion", oferta)
        self.check(
            r.status == 409 and r.es_error("OFERTA_RECIENTE"), "C-1004: 2.ª oferta -> 409 OFERTA_RECIENTE"
        )
        r = self.api("POST", f"{c}/v1/clientes/C-1003/ofertas-retencion", oferta)
        self.check(
            r.status == 409 and r.es_error("CLIENTE_EN_MORA"), "C-1003: mora > 30 -> 409 CLIENTE_EN_MORA"
        )
        return ficha

    def facturacion_casos(self) -> None:
        print("\n== Facturación ==")
        f = self.fac
        facturas = self.api("GET", f"{f}/v1/clientes/C-1001/facturas").json()
        periodos = [x["periodo"] for x in facturas]
        self.check(
            len(facturas) == 3 and periodos == sorted(periodos, reverse=True),
            "3 facturas, más recientes primero",
        )
        self.check(
            self.api("GET", f"{f}/v1/clientes/C-1001/facturas?limite=13").status == 400, "limite=13 -> 400"
        )
        saldo0 = self.api("GET", f"{f}/v1/clientes/C-1001/saldo").json()["saldo_pendiente"]
        pendiente = next(x["factura_id"] for x in facturas if x["estado"] == "pendiente")
        url = f"{f}/v1/facturas/{pendiente}/ajustes"
        r = self.api("POST", url, {"valor": 60_000, "motivo": "Compensación"})
        self.check(
            r.status == 403 and r.es_error("AJUSTE_REQUIERE_APROBACION"),
            "ajuste $60.000 sin aprobado_por -> 403 AJUSTE_REQUIERE_APROBACION",
        )
        r = self.api("POST", url, {"valor": 20_000, "motivo": "Falla de servicio"})
        self.check(r.status == 201, "ajuste $20.000 -> 201", r.texto)
        r = self.api("POST", url, {"valor": 60_000, "motivo": "Compensación", "aprobado_por": "SUP-007"})
        self.check(r.status == 201, "ajuste $60.000 con aprobado_por -> 201", r.texto)
        saldo1 = self.api("GET", f"{f}/v1/clientes/C-1001/saldo").json()["saldo_pendiente"]
        self.check(saldo1 == max(0, saldo0 - 80_000), f"saldo refleja los ajustes ({saldo0} -> {saldo1})")

    def erp_casos(self) -> None:
        print("\n== ERP ==")
        e = self.erp
        r = self.api(
            "POST",
            f"{e}/v1/ordenes-servicio",
            {"cliente_id": "C-1013", "tipo": "visita_tecnica", "prioridad": "prioritaria"},
        )
        self.check(
            r.status == 201 and r.json().get("fecha_programada") == "2026-11-19",
            "visita prioritaria -> programada a 24 h",
            r.texto,
        )
        r = self.api("POST", f"{e}/v1/ordenes-servicio", {"cliente_id": "C-1002", "tipo": "envio_equipo"})
        self.check(r.status == 400, "envío de equipo sin equipo -> 400")
        nota = {
            "factura_id": "F-5003",
            "cliente_id": "C-1001",
            "valor": 20_000,
            "motivo": "x",
            "ajuste_id": "AJ-1",
        }
        self.check(self.api("POST", f"{e}/v1/notas-credito", nota).status == 201, "nota crédito -> 201")
        r = self.api("POST", f"{e}/v1/notas-credito", nota)
        self.check(r.status == 409 and r.es_error("NOTA_CREDITO_DUPLICADA"), "nota repetida -> 409")

    def limite_429(self) -> None:
        print("\n== 429 (límite temporal de 5/min) ==")
        self.reset(self.erp)  # limpia el contador: las secciones anteriores consumieron cupo
        self.admin(self.erp, rate_limit_per_min=5, fail_rate=0)
        rs = [self.http("GET", f"{self.erp}/v1/ordenes-servicio?cliente_id=C-1013") for _ in range(6)]
        codigos = [r.status for r in rs]
        self.check(codigos == [200] * 5 + [429], f"5 x 200 y luego 429 ({codigos})")
        ra = rs[-1].headers.get("retry-after", "")
        self.check(
            ra.isdigit() and 1 <= int(ra) <= 60 and rs[-1].es_error("LIMITE_EXCEDIDO"),
            f"Retry-After={ra} s y codigo LIMITE_EXCEDIDO",
        )

    def falla_503(self, muestras: int) -> None:
        print("\n== 503 ==")
        self.admin(self.crm, fail_rate=1)
        r = self.http("GET", f"{self.crm}/v1/clientes/C-1001")
        self.check(r.status == 503 and r.es_error("SERVICIO_NO_DISPONIBLE"), "fail_rate=1 -> 503")
        self.check(
            self.http("GET", f"{self.crm}/_admin/config").status == 200, "/_admin responde con fail_rate=1"
        )
        if muestras <= 0:
            return
        self.admin(self.fac, rate_limit_per_min=1_000_000, fail_rate=0.02)
        fallas = sum(
            self.http("GET", f"{self.fac}/v1/facturas/F-5001").status == 503 for _ in range(muestras)
        )
        tasa = fallas / muestras
        # Rango amplio (≈ ±3 desviaciones para n=1000) para no dar falsos negativos.
        self.check(0.005 <= tasa <= 0.04, f"tasa de 503 con fail_rate=0.02: {fallas}/{muestras} = {tasa:.1%}")

    def logs_sin_pii(self, ficha: dict[str, Any]) -> None:
        print("\n== PII en logs de los contenedores ==")
        docker = shutil.which("docker")
        if docker is None:
            print("  OMITIDO docker no está en el PATH")
            return
        proc = subprocess.run(  # noqa: S603 - argumentos fijos, sin shell
            [docker, "compose", "logs", "--no-color", "crm-mock", "facturacion-mock", "erp-mock"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if proc.returncode != 0:
            print(f"  OMITIDO docker compose logs falló: {proc.stderr.strip()[:200]}")
            return
        logs = proc.stdout
        lineas = logs.count("\n")
        for campo in ("numero_documento", "celular", "email"):
            self.check(ficha[campo] not in logs, f"{campo} ausente en {lineas} líneas de log")
        self.check("numero_documento=" not in logs, "sin query string en los logs")

    def restaurar(self, env: dict[str, str]) -> None:
        limite = int(env.get("MOCKS_RATE_LIMIT_PER_MIN", "60"))
        fail = float(env.get("MOCKS_FAIL_RATE", "0.02"))
        for base in (self.crm, self.fac, self.erp):
            try:
                self.admin(base, rate_limit_per_min=limite, fail_rate=fail)
                self.reset(base)
            except OSError as e:
                print(f"  AVISO no se pudo restaurar {base}: {e}")
        print(f"\nRestaurado: fail_rate={fail}, rate_limit_per_min={limite}, datos reiniciados.")


def leer_env(ruta: Path) -> dict[str, str]:
    valores: dict[str, str] = {}
    if ruta.is_file():
        for linea in ruta.read_text(encoding="utf-8").splitlines():
            if "=" in linea and not linea.lstrip().startswith("#"):
                k, v = linea.split("=", 1)
                valores[k.strip()] = v.strip().strip("'\"")
    # Las variables de entorno tienen prioridad sobre .env
    valores.update({k: v for k, v in os.environ.items() if k.startswith("MOCKS_")})
    return valores


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument(
        "--env", type=Path, default=ROOT / ".env", help="Archivo .env (por defecto el de la raíz)"
    )
    ap.add_argument("--crm", default="http://127.0.0.1:8081")
    ap.add_argument("--facturacion", default="http://127.0.0.1:8082")
    ap.add_argument("--erp", default="http://127.0.0.1:8083")
    ap.add_argument(
        "--muestras-503", type=int, default=1000, help="Llamadas para medir la tasa de 503 (0 = omitir)"
    )
    ap.add_argument("--sin-logs", action="store_true", help="No revisar PII en docker compose logs")
    args = ap.parse_args()

    env = leer_env(args.env)
    api_key = env.get("MOCKS_API_KEY", "")
    if not api_key:
        print("Defina MOCKS_API_KEY en el entorno o en .env")
        return 2

    smoke = Smoke(args, api_key)
    for base in (smoke.crm, smoke.fac, smoke.erp):
        try:
            smoke.http("GET", f"{base}/health", clave=None)
        except OSError as e:
            print(f"{base} no responde ({e}). ¿Levantó los mocks con docker compose up -d?")
            return 2

    try:
        for base in (smoke.crm, smoke.fac, smoke.erp):
            smoke.admin(base, fail_rate=float(env.get("MOCKS_FAIL_RATE", "0.02")))
            smoke.reset(base)
        smoke.transversal()
        ficha = smoke.crm_casos()
        smoke.facturacion_casos()
        smoke.erp_casos()
        smoke.limite_429()
        smoke.falla_503(args.muestras_503)
        if not args.sin_logs:
            smoke.logs_sin_pii(ficha)
    finally:
        smoke.restaurar(env)

    total = smoke.ok + len(smoke.fallas)
    print(f"\nRESULTADO: {smoke.ok}/{total} OK · reintentos por 503 aleatorio: {smoke.reintentos_503}")
    for f in smoke.fallas:
        print(f"  - {f}")
    return 0 if not smoke.fallas else 1


if __name__ == "__main__":
    sys.exit(main())
