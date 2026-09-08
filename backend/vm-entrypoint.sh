#!/bin/sh
set -eu

python - <<'PY'
from urllib.parse import urlsplit

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from app.core.config import ConfigurationError, settings

problems = settings.deployment_problems()
if settings.auth_mode != "ENTRA":
    problems.append("The VM production image requires AUTH_MODE=ENTRA.")
try:
    database_url = make_url(settings.database_url)
    if database_url.drivername != "mysql+pymysql" or database_url.query.get("charset") != "utf8mb4":
        problems.append("The VM database URL must use mysql+pymysql and charset=utf8mb4.")
except (ArgumentError, ValueError):
    problems.append("DATABASE_URL is not a valid SQLAlchemy connection URL.")
if settings.storage_backend != "S3":
    problems.append("The VM production image requires STORAGE_BACKEND=S3.")
endpoint = urlsplit(settings.s3_endpoint_url or "")
if endpoint.scheme != "https" or not endpoint.hostname:
    problems.append("The VM object storage endpoint must be an HTTPS URL.")
broker = urlsplit(settings.redis_url)
if broker.scheme not in {"redis", "rediss"} or not broker.hostname:
    problems.append("REDIS_URL must name the approved external Redis service.")
if problems:
    raise ConfigurationError("\n".join(problems))
PY

exec "$@"