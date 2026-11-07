# One image: the React web app served by the FastAPI backend on a single port.
# Build from the repo root:  docker build -t researchmind .
# PORT is honoured (Railway, Render, Cloud Run...).

# ── Stage 1: Build the web app ────────────────────────────────────────────────
FROM node:20-slim AS web

WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ── Stage 2: Build Python dependencies ────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# ── Stage 3: Runtime image ────────────────────────────────────────────────────
FROM python:3.11-slim AS runner

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Non-root user
RUN useradd -r -m -u 1001 -g root appuser

# Copy installed Python packages from builder
COPY --from=builder --chown=appuser:root /root/.local /home/appuser/.local

# Copy application code and UI
COPY backend/app/ ./app/
COPY --chmod=755 backend/start.sh ./start.sh
COPY --from=web /web/dist ./web

RUN mkdir -p /app/uploads && chown -R appuser:root /app

USER appuser

ENV HOME=/home/appuser
ENV PATH=/home/appuser/.local/bin:$PATH
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV UPLOAD_DIR=/app/uploads

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -fs "http://localhost:${PORT:-8000}/health" || exit 1

CMD ["./start.sh"]
