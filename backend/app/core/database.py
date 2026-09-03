"""Engine and session factory.

The engine is built differently for SQLite and MySQL because the two fail in opposite ways. SQLite
is a file the dev server opens across threads; MySQL is a network service that silently drops idle
connections, so a pool that never checks liveness hands out a dead socket to the first request
after a quiet period - the classic "MySQL server has gone away" on the morning's first upload.
"""

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    pass


def _engine_options(database_url: str) -> dict:
    url = make_url(database_url)
    if url.get_backend_name() == "sqlite":
        # `check_same_thread` off because uvicorn serves requests from a thread pool; no pool
        # tuning, because a SQLite pool is a handle on a local file, not a network resource.
        return {"connect_args": {"check_same_thread": False}}
    options: dict = {
        "pool_pre_ping": settings.db_pool_pre_ping,
        "pool_recycle": settings.db_pool_recycle_seconds,
        "pool_size": settings.db_pool_size,
        "max_overflow": settings.db_max_overflow,
        "pool_timeout": settings.db_pool_timeout_seconds,
    }
    if url.get_backend_name() == "mysql":
        connect_args: dict = {"connect_timeout": settings.db_connect_timeout_seconds}
        # utf8mb4 is not optional here: report content is Traditional and Simplified Chinese, and
        # MySQL's legacy "utf8" is a three-byte subset that truncates anything outside the BMP.
        if "charset" not in url.query:
            connect_args["charset"] = "utf8mb4"
        options["connect_args"] = connect_args
    return options


if settings.database_url.startswith("sqlite:///") and ":memory:" not in settings.database_url:
    # sqlite creates the file but not its parent, and var/ is gitignored apart from the .gitkeep markers.
    Path(settings.database_url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(settings.database_url, echo=settings.db_echo, **_engine_options(settings.database_url))
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
