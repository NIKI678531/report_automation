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


def deep_health() -> dict:
    checks = {}
    for name, check in (("database", database_check),):
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
