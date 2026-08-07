#!/bin/sh
set -eu
cd /app/backend
python -m alembic upgrade head
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
