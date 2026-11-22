"""Arranque: python -m mocks [crm|facturacion|erp]  (o variable MOCKS_SERVICIO).

El puerto por defecto es el del contrato (8081, 8082, 8083); se cambia con MOCKS_PORT.
"""

import logging
import os
import sys

import uvicorn

from mocks import SERVICIOS


def main() -> None:
    servicio = sys.argv[1] if len(sys.argv) > 1 else os.getenv("MOCKS_SERVICIO", "crm")
    if servicio not in SERVICIOS:
        raise SystemExit(f"Servicio desconocido '{servicio}'. Opciones: {', '.join(SERVICIOS)}")
    puerto = int(os.getenv("MOCKS_PORT", SERVICIOS[servicio]))
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    uvicorn.run(
        f"mocks.{servicio}:create_app",
        factory=True,
        host=os.getenv("MOCKS_HOST", "0.0.0.0"),  # noqa: S104 - escucha dentro del contenedor # nosec B104
        port=puerto,
        # El access log de uvicorn imprime la query string (numero_documento = PII): se usa el log propio.
        access_log=False,
        server_header=False,
    )


if __name__ == "__main__":
    main()
