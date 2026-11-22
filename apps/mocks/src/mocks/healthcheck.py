"""HEALTHCHECK del contenedor sin curl: python -m mocks.healthcheck."""

import os
import sys
import urllib.request

from mocks import SERVICIOS


def main() -> int:
    servicio = os.getenv("MOCKS_SERVICIO", "crm")
    puerto = int(os.getenv("MOCKS_PORT", SERVICIOS.get(servicio, 8081)))
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{puerto}/health", timeout=3) as r:  # noqa: S310 # nosec B310
            return 0 if r.status == 200 else 1
    except OSError:
        return 1


if __name__ == "__main__":
    sys.exit(main())
