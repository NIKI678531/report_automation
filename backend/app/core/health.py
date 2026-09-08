"""Bounded, read-only dependency checks; output never includes connection details."""

from sqlalchemy import create_engine, text

from .config import settings


def database_check() -> None:
    engine = create_engine(settings.database_url, pool_pre_ping=True,
                           connect_args={"connect_timeout": 3, "read_timeout": 3, "write_timeout": 3})
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    finally:
        engine.dispose()


def storage_check() -> None:
    import boto3
    from botocore.config import Config

    client = boto3.client("s3", endpoint_url=settings.s3_endpoint_url, region_name=settings.s3_region,
                          aws_access_key_id=settings.s3_access_key_id,
                          aws_secret_access_key=settings.s3_secret_access_key,
                          config=Config(connect_timeout=3, read_timeout=3, retries={"max_attempts": 0},
                                        s3={"addressing_style": settings.s3_addressing_style}))
    try:
        client.head_bucket(Bucket=settings.s3_bucket)
    finally:
        client.close()


def deep_health() -> dict:
    checks = {}
    for name, check in (("database", database_check), ("storage", storage_check)):
        try:
            check()
            checks[name] = "ok"
        except Exception:
            # Exception text from clients often contains hosts, URLs or credentials.
            checks[name] = "unavailable"
    return {"status": "ok" if all(value == "ok" for value in checks.values()) else "degraded",
            "dependencies": checks}


if __name__ == "__main__":
    import json

    result = deep_health()
    print(json.dumps(result))
    raise SystemExit(0 if result["status"] == "ok" else 1)
