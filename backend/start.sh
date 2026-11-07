#!/bin/sh
# Container entrypoint: the FastAPI app, which also serves the React web app.
# PORT is set by hosting platforms such as Railway; defaults suit docker compose.
set -e
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers --forwarded-allow-ips="*"
