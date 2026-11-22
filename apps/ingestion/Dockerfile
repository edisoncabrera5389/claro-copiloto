# syntax=docker/dockerfile:1.7
# Imagen única de la ingesta: `watcher` o `worker` según el comando. Incluye Tesseract (spa),
# spaCy es_core_news_md y faster-whisper (el modelo de Whisper se descarga al primer audio en /modelos).

# ---------- Etapa 1: dependencias y paquete en un venv ----------
FROM python:3.15-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.13.9 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0 \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /src
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

# ---------- Etapa 2: runtime con OCR, usuario no root ----------
FROM python:3.15-slim AS runtime
LABEL org.opencontainers.image.title="claro-copiloto-ingesta" \
      org.opencontainers.image.description="Watcher y worker de ingesta: extracción, OCR, ASR, PII, chunking e indexado" \
      org.opencontainers.image.source="https://github.com/edisoncabrera5389/claro-copiloto"
RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-spa libgomp1 \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app \
 && mkdir -p /modelos /data/inbox \
 && chown 10001:10001 /modelos
COPY --from=builder --chown=root:root /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/tmp \
    HF_HOME=/modelos/hf \
    INGESTA_WHISPER_DIR=/modelos/whisper \
    INGESTA_ROL=worker
USER 10001:10001
HEALTHCHECK --interval=20s --timeout=5s --start-period=60s --retries=3 \
    CMD python -m ingesta salud --rol "$INGESTA_ROL"
CMD ["python", "-m", "ingesta", "worker"]
