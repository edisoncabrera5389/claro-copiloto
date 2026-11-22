"""Arranque: python -m copiloto_ml_service → http://0.0.0.0:8001."""

import logging
import os

import uvicorn


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")
    for ruidoso in ("mlflow", "urllib3", "httpx"):
        logging.getLogger(ruidoso).setLevel(logging.WARNING)
    uvicorn.run(
        "copiloto_ml_service.app:crear_app",
        factory=True,
        host=os.getenv("ML_HOST", "0.0.0.0"),  # noqa: S104 - dentro del contenedor
        port=int(os.getenv("ML_PORT", "8001")),
        access_log=False,
        server_header=False,
    )


if __name__ == "__main__":
    main()
