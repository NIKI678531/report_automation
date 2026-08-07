from pathlib import Path
import os
from dotenv import load_dotenv
from pydantic import BaseModel

_SERVICE_ROOT = Path(__file__).resolve().parents[2]  # backend/
_WORKSPACE_ROOT = _SERVICE_ROOT.parent  # repository root

# Load service-local secrets (FMP_API_KEY, DOWNLOAD_SECRET, ...) before any os.getenv default below.
# Real process environment always wins, so container/CI settings are never overwritten by a stray .env.
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
    fmp_api_key: str | None = os.getenv("FMP_API_KEY")
    fmp_base_url: str = os.getenv("FMP_BASE_URL", "https://financialmodelingprep.com/stable")
    fmp_timeout_seconds: float = float(os.getenv("FMP_TIMEOUT_SECONDS", "15"))
    fmp_max_results: int = int(os.getenv("FMP_MAX_RESULTS", "100"))
    fmp_allowed_hosts: tuple[str, ...] = tuple(filter(None, (item.strip().lower() for item in os.getenv("FMP_ALLOWED_HOSTS", "financialmodelingprep.com").split(","))))
    # Which adapter in app.integrations.news.REGISTRY answers a fetch that names no provider.
    news_provider: str = os.getenv("NEWS_PROVIDER", "FMP")
    marketaux_api_key: str | None = os.getenv("MARKETAUX_API_KEY")
    marketaux_base_url: str = os.getenv("MARKETAUX_BASE_URL", "https://api.marketaux.com/v1")
    marketaux_timeout_seconds: float = float(os.getenv("MARKETAUX_TIMEOUT_SECONDS", "15"))
    marketaux_max_results: int = int(os.getenv("MARKETAUX_MAX_RESULTS", "100"))
    marketaux_language: str = os.getenv("MARKETAUX_LANGUAGE", "en")
    marketaux_allowed_hosts: tuple[str, ...] = tuple(filter(None, (item.strip().lower() for item in os.getenv("MARKETAUX_ALLOWED_HOSTS", "api.marketaux.com").split(","))))
    workspace_root: Path = _WORKSPACE_ROOT
    # backend/ itself: test fixtures and alembic live under the service, not the repository root.
    service_root: Path = _SERVICE_ROOT

    @property
    def output_root(self) -> Path:
        return self.workspace_root / "var" / "output"


settings = Settings()
