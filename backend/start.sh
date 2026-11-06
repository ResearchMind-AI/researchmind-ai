#!/bin/sh
# Container entrypoint. APP_MODE=ui runs the Streamlit UI, anything else the API.
# PORT is set by hosting platforms such as Railway; defaults suit docker compose.
set -e
if [ "${APP_MODE:-api}" = "ui" ]; then
  exec streamlit run ui/app.py --server.port "${PORT:-8501}" --server.address 0.0.0.0
else
  exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
fi
