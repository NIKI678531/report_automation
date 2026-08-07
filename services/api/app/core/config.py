from pathlib import Path
import os
from pydantic import BaseModel


class Settings(BaseModel):
    app_name: str = "Monthly Commentary API"
    api_prefix: str = "/api/v1"
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./commentary.db")
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
    workspace_root: Path = Path(__file__).resolve().parents[4]

    @property
    def output_root(self) -> Path:
        return self.workspace_root / "output"


settings = Settings()
