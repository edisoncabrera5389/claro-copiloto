"""Métricas Prometheus del worker de ingesta, con la librería estándar (formato de texto 0.0.4).

Sin dependencias nuevas: la imagen de ingesta (spaCy, Whisper, Tesseract) no se reconstruye desde cero.
Expone en :9101/metrics la frescura (KPI ≤ 15 min), los resultados por documento, los errores y la cola.
"""

import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CUBETAS_FRESCURA = (1, 2, 5, 10, 30, 60, 120, 300, 600, 900, 1800)


class Metricas:
    def __init__(self, cola: Callable[[], dict[str, float]] | None = None):
        self._bloqueo = threading.Lock()
        self.documentos: dict[str, int] = {}
        self.errores = 0
        self.frescura_cubetas = [0] * len(CUBETAS_FRESCURA)
        self.frescura_suma = 0.0
        self.frescura_cuenta = 0
        self.frescura_ultima: float | None = None
        self._cola = cola  # se consulta al leer: pendientes y dead-letter

    def documento(self, resultado: str, frescura_s: float | None) -> None:
        with self._bloqueo:
            self.documentos[resultado] = self.documentos.get(resultado, 0) + 1
            if frescura_s is not None:
                self.frescura_ultima = frescura_s
                self.frescura_suma += frescura_s
                self.frescura_cuenta += 1
                for i, limite in enumerate(CUBETAS_FRESCURA):
                    if frescura_s <= limite:
                        self.frescura_cubetas[i] += 1

    def error(self) -> None:
        with self._bloqueo:
            self.errores += 1

    def texto(self) -> str:
        with self._bloqueo:
            lineas = [
                "# HELP ingesta_documentos_total Documentos procesados por resultado",
                "# TYPE ingesta_documentos_total counter",
                *(
                    f'ingesta_documentos_total{{resultado="{r}"}} {n}'
                    for r, n in sorted(self.documentos.items())
                ),
                "# HELP ingesta_errores_total Intentos de procesamiento fallidos",
                "# TYPE ingesta_errores_total counter",
                f"ingesta_errores_total {self.errores}",
                "# HELP ingesta_frescura_segundos Detectado en la carpeta -> buscable en el índice",
                "# TYPE ingesta_frescura_segundos histogram",
                *(
                    f'ingesta_frescura_segundos_bucket{{le="{float(limite)}"}} {self.frescura_cubetas[i]}'
                    for i, limite in enumerate(CUBETAS_FRESCURA)
                ),
                f'ingesta_frescura_segundos_bucket{{le="+Inf"}} {self.frescura_cuenta}',
                f"ingesta_frescura_segundos_sum {self.frescura_suma}",
                f"ingesta_frescura_segundos_count {self.frescura_cuenta}",
            ]
            if self.frescura_ultima is not None:
                lineas += [
                    "# HELP ingesta_frescura_ultima_segundos Frescura del último documento indexado",
                    "# TYPE ingesta_frescura_ultima_segundos gauge",
                    f"ingesta_frescura_ultima_segundos {self.frescura_ultima}",
                ]
        try:
            for nombre, valor in (self._cola() if self._cola else {}).items():
                lineas += [f"# TYPE ingesta_cola_{nombre} gauge", f"ingesta_cola_{nombre} {valor}"]
        except Exception:  # noqa: BLE001, S110 - sin Redis se omiten las métricas de cola
            pass
        return "\n".join(lineas) + "\n"

    def servir(self, puerto: int) -> ThreadingHTTPServer:
        metricas = self

        class Manejador(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 - nombre exigido por http.server
                if self.path != "/metrics":
                    self.send_error(404)
                    return
                cuerpo = metricas.texto().encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
                self.send_header("Content-Length", str(len(cuerpo)))
                self.end_headers()
                self.wfile.write(cuerpo)

            def log_message(self, *args: object) -> None:  # sin ruido en el log del worker
                return

        servidor = ThreadingHTTPServer(("0.0.0.0", puerto), Manejador)  # noqa: S104 - red interna de Docker
        threading.Thread(target=servidor.serve_forever, daemon=True).start()
        return servidor
