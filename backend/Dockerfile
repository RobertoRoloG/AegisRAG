# ============================================================
# AegisRAG — Dockerfile del Backend
# Multi-stage build optimizado para producción.
# ============================================================

# --- Stage 1: Dependencias ---
FROM python:3.11-slim AS dependencies

WORKDIR /tmp

# Instalar dependencias del sistema necesarias para compilar asyncpg
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# --- Stage 2: Runtime ---
FROM python:3.11-slim AS runtime

WORKDIR /app

# Solo las libs runtime necesarias (sin compiladores)
RUN apt-get update && \
    apt-get install -y --no-install-recommends libpq5 curl && \
    rm -rf /var/lib/apt/lists/*

# Copiar dependencias pre-compiladas del stage anterior
COPY --from=dependencies /install /usr/local

# Copiar código fuente
COPY . .

# Puerto de la API
EXPOSE 8000

# Health check del contenedor
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -sf http://localhost:8000/api/v1/health || exit 1

# Ejecutar con Uvicorn (workers configurables via ENV)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
