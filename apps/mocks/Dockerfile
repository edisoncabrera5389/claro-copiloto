# syntax=docker/dockerfile:1.7
# Imagen única para los 3 mocks; el servicio se elige con MOCKS_SERVICIO (crm | facturacion | erp).

# ---------- Etapa 1: dependencias y paquete en un venv ----------
FROM python:3.15-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.13.9 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0 \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /src
# Primero solo el lock: la capa de dependencias se reutiliza si el código cambia.
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

# ---------- Etapa 2: runtime mínimo, sin uv ni código fuente, usuario no root ----------
FROM python:3.15-slim AS runtime
LABEL org.opencontainers.image.title="claro-copiloto-mocks" \
      org.opencontainers.image.description="CRM, Facturación y ERP simulados de Claro Copiloto" \
      org.opencontainers.image.source="https://github.com/edisoncabrera5389/claro-copiloto"
RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app
COPY --from=builder --chown=root:root /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    MOCKS_SERVICIO=crm \
    MOCKS_DATA_DIR=/data
USER 10001:10001
EXPOSE 8081 8082 8083
HEALTHCHECK --interval=15s --timeout=4s --start-period=10s --retries=3 \
    CMD ["python", "-m", "mocks.healthcheck"]
CMD ["python", "-m", "mocks"]
