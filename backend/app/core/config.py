from pathlib import Path
import os
import tempfile
from dotenv import load_dotenv
from pydantic import BaseModel

_SERVICE_ROOT = Path(__file__).resolve().parents[2]  # backend/
_WORKSPACE_ROOT = _SERVICE_ROOT.parent  # repository root
_LOCAL_DA_REPORT_CANDIDATES = (_WORKSPACE_ROOT / "da_report.sqlite", Path.home() / "Downloads" / "da_report.sqlite")

# Load service-local secrets (MARKETAUX_API_KEY, DOWNLOAD_SECRET, ...) before any os.getenv default
# below. Real process environment always wins, so container/CI settings are never overwritten by a
# stray .env.
load_dotenv(_SERVICE_ROOT / ".env", override=False)


class Settings(BaseModel):
    app_name: str = "Monthly Commentary API"
    api_prefix: str = "/api/v1"
    # Anchored to this file instead of the CWD: alembic runs from backend/ while uvicorn runs from the
    # repository root, and a relative sqlite URL made each of them create its own stray database file.
    database_url: str = os.getenv("DATABASE_URL", f"sqlite:///{(_WORKSPACE_ROOT / 'var' / 'commentary.db').as_posix()}")
    template_version: str = "3033-v2"
    renderer_version: str = "chromium-v1"
    auth_mode: str = os.getenv("AUTH_MODE", "LOCAL")  # Set to ENTRA in deployed environments after configuring token validation.
    task_mode: str = os.getenv("TASK_MODE", "EAGER")
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    storage_backend: str = os.getenv("STORAGE_BACKEND", "LOCAL")
    download_secret: str = os.getenv("DOWNLOAD_SECRET", "local-development-secret-change-me")
    download_ttl_seconds: int = int(os.getenv("DOWNLOAD_TTL_SECONDS", "300"))
    # Which adapter in app.integrations.news.REGISTRY answers a fetch that names no provider.
    news_provider: str = os.getenv("NEWS_PROVIDER", "DA_REPORT")
    marketaux_api_key: str | None = os.getenv("MARKETAUX_API_KEY")
    marketaux_base_url: str = os.getenv("MARKETAUX_BASE_URL", "https://api.marketaux.com/v1")
    marketaux_timeout_seconds: float = float(os.getenv("MARKETAUX_TIMEOUT_SECONDS", "15"))
    marketaux_max_results: int = int(os.getenv("MARKETAUX_MAX_RESULTS", "100"))
    marketaux_language: str = os.getenv("MARKETAUX_LANGUAGE", "en")
    marketaux_allowed_hosts: tuple[str, ...] = tuple(filter(None, (item.strip().lower() for item in os.getenv("MARKETAUX_ALLOWED_HOSTS", "api.marketaux.com").split(","))))
    da_report_sqlite_path: Path | None = (
        Path(os.environ["DA_REPORT_SQLITE_PATH"]).expanduser()
        if os.getenv("DA_REPORT_SQLITE_PATH")
        else next((path for path in _LOCAL_DA_REPORT_CANDIDATES if path.is_file()), None)
    )
    da_report_sqlite_sha256: str | None = os.getenv("DA_REPORT_SQLITE_SHA256")
    da_report_object_url: str | None = os.getenv("DA_REPORT_OBJECT_URL")
    da_report_cache_dir: Path = Path(os.getenv("DA_REPORT_CACHE_DIR", str(Path(tempfile.gettempdir()) / "commentary-da")))
    da_report_max_bytes: int = int(os.getenv("DA_REPORT_MAX_BYTES", str(512 * 1024 * 1024)))
    da_report_timeout_seconds: float = float(os.getenv("DA_REPORT_TIMEOUT_SECONDS", "10"))
    da_report_auto_load: bool = os.getenv("DA_REPORT_AUTO_LOAD", "true").strip().lower() in {"1", "true", "yes", "y"}
    # The TESTING lane binds the golden fixture — data that was transcribed from an approved report
    # rather than derived from a source system. Off by default so a deployed environment cannot
    # produce a fixture-backed report by accident; local and CI turn it on deliberately.
    allow_testing_lane: bool = os.getenv("ALLOW_TESTING_LANE", "false").strip().lower() in {"1", "true", "yes", "y"}
    workspace_root: Path = _WORKSPACE_ROOT
    # backend/ itself: test fixtures and alembic live under the service, not the repository root.
    service_root: Path = _SERVICE_ROOT

    @property
    def output_root(self) -> Path:
        return self.workspace_root / "var" / "output"


settings = Settings()
