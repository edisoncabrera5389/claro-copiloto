"""Arranque: python -m copiloto_api → http://0.0.0.0:8000 (docs en /docs)."""

import logging
import os

import uvicorn


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    for ruidoso in ("httpx", "openai", "mcp", "fastmcp"):
        logging.getLogger(ruidoso).setLevel(logging.WARNING)
    uvicorn.run(
        "copiloto_api.main:crear_app",
        factory=True,
        host=os.getenv("API_HOST", "0.0.0.0"),  # noqa: S104 - dentro del contenedor
        port=int(os.getenv("API_PORT", "8000")),
        access_log=False,
        server_header=False,
    )


if __name__ == "__main__":
    main()
