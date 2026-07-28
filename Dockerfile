# syntax=docker/dockerfile:1

# ─── Stage 1: build delle dipendenze ────────────────────────────────────────
# Alcune dipendenze di chromadb non hanno wheel per tutte le piattaforme:
# i compilatori restano in questo stage e non finiscono nell'immagine finale.
FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential gcc g++ \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt


# ─── Stage 2: runtime ───────────────────────────────────────────────────────
FROM python:3.11-slim

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DATA_DIR=/data \
    DOCS_DIR=/documents \
    ANONYMIZED_TELEMETRY=False

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv

WORKDIR /srv
COPY app ./app

# I volumi sono montati dall'host: l'utente non-root deve poterci scrivere.
# Vedi la nota PUID/PGID nel README se il NAS usa uid diversi.
RUN useradd -u 1000 -m appuser && mkdir -p /data /documents && chown -R appuser /data /srv
USER appuser

EXPOSE 8000
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
