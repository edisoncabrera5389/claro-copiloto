"""Arranque: python -m copiloto_mcp  → MCP por HTTP (streamable) en http://0.0.0.0:8090/mcp."""

import logging

from copiloto_mcp.config import Settings
from copiloto_mcp.server import crear_servidor


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    settings = Settings()
    crear_servidor(settings).run(
        transport="http",
        host=settings.host,
        port=settings.port,
        show_banner=False,
        # Sin access log de uvicorn: el healthcheck cada 15 s tapa el tráfico. Las tools las registra
        # RegistroTools.
        uvicorn_config={"access_log": False},
    )


if __name__ == "__main__":
    main()
