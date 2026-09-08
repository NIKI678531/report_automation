"""Image startup contract, shared by migrations and the API."""

from urllib.parse import urlsplit

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from .config import ConfigurationError, settings


def verify_container_configuration() -> None:
    problems = settings.deployment_problems()
    if settings.auth_mode not in {"REMOTE", "ENTRA"}:
        problems.append("The deployment image requires AUTH_MODE=REMOTE or ENTRA.")
    try:
        database = make_url(settings.database_url)
        if database.drivername != "mysql+pymysql" or database.query.get("charset") != "utf8mb4":
            problems.append("DATABASE_URL must use mysql+pymysql and charset=utf8mb4.")
        if not database.host or not database.database or not database.username or not database.password:
            problems.append("DATABASE_URL requires a host, database and credentials.")
    except (ArgumentError, ValueError):
        problems.append("DATABASE_URL is not a valid SQLAlchemy connection URL.")
    if settings.storage_backend != "S3":
        problems.append("The deployment image requires STORAGE_BACKEND=S3.")
    try:
        endpoint = urlsplit(settings.s3_endpoint_url or "")
        if settings.s3_endpoint_url and (endpoint.scheme != "https" or not endpoint.hostname):
            problems.append("S3_ENDPOINT_URL must use HTTPS.")
    except ValueError:
        problems.append("S3_ENDPOINT_URL is malformed.")
    if problems:
        raise ConfigurationError("\n".join(problems))


if __name__ == "__main__":
    verify_container_configuration()
