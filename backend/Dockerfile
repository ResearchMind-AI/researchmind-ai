# One image, two processes: the FastAPI backend (default) and the Streamlit UI
# (run with: streamlit run ui/app.py). docker-compose files choose which.

# ── Stage 1: Build dependencies ───────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# ── Stage 2: Runtime image ────────────────────────────────────────────────────
FROM python:3.11-slim AS runner

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Non-root user with a home directory (Streamlit writes small files there)
RUN useradd -r -m -u 1001 -g root appuser

# Copy installed Python packages from builder
COPY --from=builder --chown=appuser:root /root/.local /home/appuser/.local

# Copy application code and UI
COPY app/ ./app/
COPY ui/ ./ui/
COPY .streamlit/ ./.streamlit/

RUN mkdir -p /app/uploads && chown -R appuser:root /app

USER appuser

ENV HOME=/home/appuser
ENV PATH=/home/appuser/.local/bin:$PATH
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV UPLOAD_DIR=/app/uploads

EXPOSE 8000 8501

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/health || curl -f http://localhost:8501/_stcore/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
