#!/bin/sh
set -eu
cd /app/backend
python -m alembic upgrade head
# --proxy-headers so the app sees the browser's scheme and address rather than nginx's; without it
# every request is logged as coming from the proxy over plain http. FORWARDED_ALLOW_IPS is
# restricted to the reverse proxy: trusting X-Forwarded-For from an arbitrary source lets a caller
# choose the address that ends up in the logs.
exec uvicorn app.main:app \
  --host 0.0.0.0 \
  --port 8000 \
  --proxy-headers \
  --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-*}"
