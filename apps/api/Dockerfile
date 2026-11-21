# syntax=docker/dockerfile:1.7
# API FastAPI + agente LangGraph (puerto 8000). El modelo del reranker (opcional) se descarga a /modelos.

FROM python:3.12-slim AS builder
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

FROM python:3.12-slim AS runtime
LABEL org.opencontainers.image.title="claro-copiloto-api" \
      org.opencontainers.image.description="API y agente de Claro Copiloto (LangGraph, RAG híbrido, guardrails)" \
      org.opencontainers.image.source="https://github.com/edisoncabrera5389/claro-copiloto"
RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app \
 && mkdir -p /modelos && chown 10001:10001 /modelos
COPY --from=builder --chown=root:root /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/tmp \
    HF_HOME=/modelos/hf \
    API_MODELOS_DIR=/modelos/fastembed
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=4s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health/vivo', timeout=3).status == 200 else 1)"]
CMD ["python", "-m", "copiloto_api"]
