from pathlib import Path
import os
import tempfile
from urllib.parse import urlsplit
from dotenv import load_dotenv
from pydantic import BaseModel, Field

_SERVICE_ROOT = Path(__file__).resolve().parents[2]  # backend/
_WORKSPACE_ROOT = _SERVICE_ROOT.parent  # repository root

# Load service-local secrets (DATAWAREHOUSE_MYSQL_PASSWORD, MARKETAUX_API_KEY, ...) before defaults
# below. Real process environment always wins, so container/CI settings are never overwritten by a
# stray .env.
load_dotenv(_SERVICE_ROOT / ".env", override=False)

DEFAULT_DOWNLOAD_SECRET = "local-development-secret-change-me"
# Backends `app.core.storage` actually implements. A value outside this list used to fall through
# to local disk without a word, so `STORAGE_BACKEND=TOS` looked configured and stored nothing.
SUPPORTED_STORAGE_BACKENDS = ("LOCAL", "S3")
# The one auth mode that trusts request headers. Everything that is only safe on a developer
# workstation - home-directory probing, header-supplied identity, the public default signing key -
# is gated on this single value. REMOTE is a deployment, not a LOCAL exemption.
_LOCAL_AUTH_MODE = "LOCAL"


class ConfigurationError(RuntimeError):
    """A deployment setting is missing, unparseable or unsafe for the selected auth mode."""


def _env_str(name: str, default: str) -> str:
    value = os.getenv(name)
    return default if value is None or not value.strip() else value.strip()


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    normalized = raw.strip().casefold()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    raise ConfigurationError(f"{name} must be a boolean (true/false), got {raw!r}.")


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw.strip())
    except ValueError as error:
        # Import-time int(os.getenv(...)) used to crash the app *and* alembic with a bare ValueError
        # that named neither the variable nor the value. Both now say which setting to fix.
        raise ConfigurationError(f"{name} must be an integer, got {raw!r}.") from error


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw.strip())
    except ValueError as error:
        raise ConfigurationError(f"{name} must be a number, got {raw!r}.") from error


def _env_csv(name: str, default: str) -> tuple[str, ...]:
    return tuple(filter(None, (item.strip().casefold() for item in _env_str(name, default).split(","))))


def _env_path(name: str) -> Path | None:
    raw = os.getenv(name)
    return Path(raw).expanduser() if raw and raw.strip() else None


def _developer_snapshot(name: str, candidates: tuple[Path, ...]) -> Path | None:
    """Resolve an offline snapshot path, probing developer locations only in LOCAL auth mode.

    A deployed process must state its snapshot explicitly. Probing ``~/Downloads`` there would let
    a file that merely happens to exist on the host become an authoritative data source.
    """
    explicit = _env_path(name)
    if explicit is not None:
        return explicit
    if _env_str("AUTH_MODE", _LOCAL_AUTH_MODE).upper() != _LOCAL_AUTH_MODE:
        return None
    return next((path for path in candidates if path.is_file()), None)


_LOCAL_DA_REPORT_CANDIDATES = (_WORKSPACE_ROOT / "da_report.sqlite", Path.home() / "Downloads" / "da_report.sqlite")
_LOCAL_DATAWAREHOUSE_CANDIDATES = (
    Path.home() / "Downloads" / "td_attribution_cdb_test_2025" / "td_attribution_cdb_test_2025.db",
    Path.home() / "Downloads" / "DB_2025" / "td_attribution_cdb_test_2025.db",
)


class Settings(BaseModel):
    app_name: str = "Monthly Commentary API"
    api_prefix: str = "/api/v1"
    # Anchored to this file instead of the CWD: alembic runs from backend/ while uvicorn runs from the
    # repository root, and a relative sqlite URL made each of them create its own stray database file.
    database_url: str = _env_str("DATABASE_URL", f"sqlite:///{(_WORKSPACE_ROOT / 'var' / 'commentary.db').as_posix()}")
    # MySQL closes idle connections after `wait_timeout` (8h by default, minutes behind most load
    # balancers). Without pre-ping the first request after an idle period fails with "server has
    # gone away"; recycling below the server's timeout keeps the pool from holding dead sockets.
    db_pool_pre_ping: bool = _env_bool("DB_POOL_PRE_PING", True)
    db_pool_recycle_seconds: int = _env_int("DB_POOL_RECYCLE_SECONDS", 1800)
    db_pool_size: int = _env_int("DB_POOL_SIZE", 5)
    db_max_overflow: int = _env_int("DB_MAX_OVERFLOW", 10)
    db_pool_timeout_seconds: int = _env_int("DB_POOL_TIMEOUT_SECONDS", 30)
    db_connect_timeout_seconds: int = _env_int("DB_CONNECT_TIMEOUT_SECONDS", 10)
    db_echo: bool = _env_bool("DB_ECHO", False)
    template_version: str = "3033-v2"
    renderer_version: str = "chromium-v1"
    # REMOTE is a shared application identity behind the existing remote application platform.
    auth_mode: str = _env_str("AUTH_MODE", _LOCAL_AUTH_MODE).upper()
    task_mode: str = _env_str("TASK_MODE", "EAGER").upper()
    translation_provider: str = _env_str("TRANSLATION_PROVIDER", "DISABLED").upper()
    translation_base_url: str = _env_str("TRANSLATION_BASE_URL", "")
    translation_model: str = _env_str("TRANSLATION_MODEL", "")
    translation_api_key: str = Field(default=_env_str("TRANSLATION_API_KEY", ""), repr=False)
    translation_timeout_seconds: float = _env_float("TRANSLATION_TIMEOUT_SECONDS", 45)
    translation_max_characters: int = _env_int("TRANSLATION_MAX_CHARACTERS", 30000)
    translation_max_tokens: int = _env_int("TRANSLATION_MAX_TOKENS", 16000)
    storage_backend: str = _env_str("STORAGE_BACKEND", "LOCAL").upper()
    # S3-compatible object storage: Volcengine TOS, MinIO and AWS S3 all speak this API. A bucket
    # is the only hard requirement; credentials may instead come from the pod's assumed role, and
    # the endpoint is only needed for a vendor that is not AWS.
    s3_bucket: str | None = os.getenv("S3_BUCKET")
    s3_endpoint_url: str | None = os.getenv("S3_ENDPOINT_URL")
    s3_region: str | None = os.getenv("S3_REGION")
    # Every artifact key is written below this prefix, so one bucket can hold several environments.
    s3_prefix: str = _env_str("S3_PREFIX", "")
    s3_access_key_id: str | None = Field(default=os.getenv("S3_ACCESS_KEY_ID"), repr=False)
    s3_secret_access_key: str | None = Field(default=os.getenv("S3_SECRET_ACCESS_KEY"), repr=False)
    # `virtual` is bucket.endpoint (TOS, AWS); `path` is endpoint/bucket (MinIO and most gateways).
    s3_addressing_style: str = _env_str("S3_ADDRESSING_STYLE", "virtual")
    download_secret: str = _env_str("DOWNLOAD_SECRET", DEFAULT_DOWNLOAD_SECRET)
    download_ttl_seconds: int = _env_int("DOWNLOAD_TTL_SECONDS", 300)
    # Microsoft Entra ID. `entra_audience` is the API's application ID URI or client id; a token
    # minted for another audience is a token for another service and is rejected. Leaving the
    # issuer unset derives the standard v2.0 issuer from the tenant.
    entra_tenant_id: str | None = os.getenv("ENTRA_TENANT_ID")
    entra_audience: str | None = os.getenv("ENTRA_AUDIENCE")
    entra_issuer: str | None = os.getenv("ENTRA_ISSUER")
    entra_jwks_url: str | None = os.getenv("ENTRA_JWKS_URL")
    entra_jwks_cache_seconds: int = _env_int("ENTRA_JWKS_CACHE_SECONDS", 3600)
    entra_jwks_timeout_seconds: float = _env_float("ENTRA_JWKS_TIMEOUT_SECONDS", 5.0)
    entra_leeway_seconds: int = _env_int("ENTRA_LEEWAY_SECONDS", 60)
    # Which claim carries the application role. Entra puts app-role assignments in `roles`.
    entra_role_claim: str = _env_str("ENTRA_ROLE_CLAIM", "roles")
    # Which claim carries the product scope. Absent means the token grants no product scope, and
    # every report query returns empty rather than everything.
    entra_product_scope_claim: str = _env_str("ENTRA_PRODUCT_SCOPE_CLAIM", "product_scope")
    entra_allowed_algorithms: tuple[str, ...] = tuple(
        item.upper() for item in _env_csv("ENTRA_ALLOWED_ALGORITHMS", "RS256")
    )
    # Upload ceilings, enforced while streaming rather than after buffering the whole body.
    # nginx `client_max_body_size` must be at least as large or the proxy rejects first with a 413
    # that carries none of the structured error envelope.
    upload_max_bytes: int = _env_int("UPLOAD_MAX_BYTES", 20 * 1024 * 1024)
    upload_batch_max_files: int = _env_int("UPLOAD_BATCH_MAX_FILES", 20)
    upload_batch_max_bytes: int = _env_int("UPLOAD_BATCH_MAX_BYTES", 100 * 1024 * 1024)
    catalog_upload_max_bytes: int = _env_int("CATALOG_UPLOAD_MAX_BYTES", 5 * 1024 * 1024)
    cors_allow_origins: tuple[str, ...] = tuple(
        item for item in (part.strip() for part in _env_str("CORS_ALLOW_ORIGINS", "http://localhost:5173").split(",")) if item
    )
    # Which adapter in app.integrations.news.REGISTRY answers a fetch that names no provider.
    news_provider: str = _env_str("NEWS_PROVIDER", "DA_REPORT")
    marketaux_api_key: str | None = Field(default=os.getenv("MARKETAUX_API_KEY"), repr=False)
    marketaux_base_url: str = _env_str("MARKETAUX_BASE_URL", "https://api.marketaux.com/v1")
    marketaux_timeout_seconds: float = _env_float("MARKETAUX_TIMEOUT_SECONDS", 15)
    marketaux_max_results: int = _env_int("MARKETAUX_MAX_RESULTS", 100)
    marketaux_language: str = _env_str("MARKETAUX_LANGUAGE", "en")
    marketaux_allowed_hosts: tuple[str, ...] = _env_csv("MARKETAUX_ALLOWED_HOSTS", "api.marketaux.com")
    da_report_sqlite_path: Path | None = _developer_snapshot("DA_REPORT_SQLITE_PATH", _LOCAL_DA_REPORT_CANDIDATES)
    da_report_sqlite_sha256: str | None = os.getenv("DA_REPORT_SQLITE_SHA256")
    da_report_object_url: str | None = os.getenv("DA_REPORT_OBJECT_URL")
    da_report_cache_dir: Path = Path(_env_str("DA_REPORT_CACHE_DIR", str(Path(tempfile.gettempdir()) / "commentary-da")))
    da_report_max_bytes: int = _env_int("DA_REPORT_MAX_BYTES", 512 * 1024 * 1024)
    da_report_timeout_seconds: float = _env_float("DA_REPORT_TIMEOUT_SECONDS", 10)
    da_report_auto_load: bool = _env_bool("DA_REPORT_AUTO_LOAD", True)
    datawarehouse_performance_enabled: bool = _env_bool("DATAWAREHOUSE_PERFORMANCE_ENABLED", True)
    # Production Historical Performance reads the approved CDB views through a dedicated read-only
    # MySQL identity.  Keep credentials in the process secret store; the SQLite settings below are
    # an offline/test fallback and are used only when no MySQL host is configured.
    datawarehouse_mysql_host: str | None = os.getenv("DATAWAREHOUSE_MYSQL_HOST")
    datawarehouse_mysql_port: int = _env_int("DATAWAREHOUSE_MYSQL_PORT", 3306)
    datawarehouse_mysql_database: str | None = os.getenv("DATAWAREHOUSE_MYSQL_DATABASE")
    datawarehouse_mysql_username: str | None = os.getenv("DATAWAREHOUSE_MYSQL_USERNAME")
    datawarehouse_mysql_password: str | None = Field(
        default=os.getenv("DATAWAREHOUSE_MYSQL_PASSWORD"), repr=False,
    )
    datawarehouse_mysql_ssl_ca: Path | None = _env_path("DATAWAREHOUSE_MYSQL_SSL_CA")
    datawarehouse_mysql_ssl_verify_identity: bool = _env_bool("DATAWAREHOUSE_MYSQL_SSL_VERIFY_IDENTITY", True)
    datawarehouse_class_master_view: str = _env_str(
        "DATAWAREHOUSE_CLASS_MASTER_VIEW", "view_ads_busi_product_fundinfo_class_f_p"
    )
    datawarehouse_fund_returns_view: str = _env_str(
        "DATAWAREHOUSE_FUND_RETURNS_VIEW", "view_ads_busi_performance_class_returns_f_p"
    )
    datawarehouse_index_returns_view: str = _env_str(
        "DATAWAREHOUSE_INDEX_RETURNS_VIEW", "view_ads_busi_performance_index_returns_f_p"
    )
    datawarehouse_constituents_enabled: bool = _env_bool("DATAWAREHOUSE_CONSTITUENTS_ENABLED", True)
    datawarehouse_constituents_view: str = _env_str(
        "DATAWAREHOUSE_CONSTITUENTS_VIEW", "view_ads_busi_market_index_constituent_price_daily_f_p"
    )
    # Existing approved fund-level valuation view. This can supply AUM independently while the
    # unified daily KPI/calendar contract below is being provisioned.
    datawarehouse_fund_aum_view: str | None = _env_str(
        "DATAWAREHOUSE_FUND_AUM_VIEW", "view_ads_busi_valuation_nav_fund_level_exposure_1_f_p"
    )
    # Optional unified CDB contract for Portfolio Analysis. When configured, it is authoritative
    # for both fund_kpi_daily and trading_calendar; DA-Report is not used as a silent fallback.
    datawarehouse_fund_kpi_view: str | None = os.getenv("DATAWAREHOUSE_FUND_KPI_VIEW")
    datawarehouse_sqlite_path: Path | None = _developer_snapshot(
        "DATAWAREHOUSE_SQLITE_PATH", _LOCAL_DATAWAREHOUSE_CANDIDATES
    )
    datawarehouse_sqlite_sha256: str | None = os.getenv("DATAWAREHOUSE_SQLITE_SHA256")
    datawarehouse_object_url: str | None = os.getenv("DATAWAREHOUSE_OBJECT_URL")
    datawarehouse_cache_dir: Path = Path(
        _env_str("DATAWAREHOUSE_CACHE_DIR", str(Path(tempfile.gettempdir()) / "commentary-datawarehouse"))
    )
    datawarehouse_max_bytes: int = _env_int("DATAWAREHOUSE_MAX_BYTES", 1024 * 1024 * 1024)
    datawarehouse_timeout_seconds: float = _env_float("DATAWAREHOUSE_TIMEOUT_SECONDS", 15)
    fmp_constituent_returns_enabled: bool = _env_bool("FMP_CONSTITUENT_RETURNS_ENABLED", True)
    fmp_api_key: str | None = Field(default=os.getenv("FMP_API_KEY"), repr=False)
    fmp_base_url: str = _env_str("FMP_BASE_URL", "https://financialmodelingprep.com/stable")
    fmp_timeout_seconds: float = _env_float("FMP_TIMEOUT_SECONDS", 20)
    fmp_boundary_lookback_days: int = _env_int("FMP_BOUNDARY_LOOKBACK_DAYS", 14)
    fmp_allowed_hosts: tuple[str, ...] = _env_csv("FMP_ALLOWED_HOSTS", "financialmodelingprep.com")
    # The TESTING lane binds the golden fixture — data that was transcribed from an approved report
    # rather than derived from a source system. Off by default so a deployed environment cannot
    # produce a fixture-backed report by accident; local and CI turn it on deliberately.
    allow_testing_lane: bool = _env_bool("ALLOW_TESTING_LANE", False)
    workspace_root: Path = _WORKSPACE_ROOT
    # backend/ itself: test fixtures and alembic live under the service, not the repository root.
    service_root: Path = _SERVICE_ROOT

    @property
    def output_root(self) -> Path:
        return self.workspace_root / "var" / "output"

    @property
    def is_local_auth(self) -> bool:
        """True when identity comes from request headers instead of a validated token."""
        return self.auth_mode == _LOCAL_AUTH_MODE

    @property
    def resolved_entra_issuer(self) -> str | None:
        if self.entra_issuer:
            return self.entra_issuer
        return f"https://login.microsoftonline.com/{self.entra_tenant_id}/v2.0" if self.entra_tenant_id else None

    @property
    def resolved_entra_jwks_url(self) -> str | None:
        if self.entra_jwks_url:
            return self.entra_jwks_url
        return (
            f"https://login.microsoftonline.com/{self.entra_tenant_id}/discovery/v2.0/keys"
            if self.entra_tenant_id
            else None
        )

    def deployment_problems(self) -> list[str]:
        """Every reason this configuration must not serve traffic, in one pass.

        Returned rather than raised so the caller can log all of them at once; ``create_app``
        turns a non-empty list into a startup failure. LOCAL is exempt by design: it is the
        developer mode where headers are the identity and the signing key is public.
        """
        problems: list[str] = []
        if self.task_mode != "EAGER":
            problems.append("TASK_MODE must be EAGER; queue execution is no longer installed (ADR-0028).")
        if self.is_local_auth:
            return problems
        if self.download_secret == DEFAULT_DOWNLOAD_SECRET:
            problems.append(
                "DOWNLOAD_SECRET is still the public repository default; anyone can mint a valid "
                "artifact download signature. Set it from the secret store."
            )
        if len(self.download_secret) < 32:
            problems.append("DOWNLOAD_SECRET must be at least 32 characters of high-entropy secret.")
        if self.auth_mode not in {"ENTRA", "REMOTE"}:
            problems.append(f"AUTH_MODE must be LOCAL, REMOTE or ENTRA, got {self.auth_mode!r}.")
        elif self.auth_mode == "ENTRA":
            if not self.entra_audience:
                problems.append("ENTRA_AUDIENCE is required so tokens minted for another API are rejected.")
            if not self.resolved_entra_issuer:
                problems.append("ENTRA_TENANT_ID or ENTRA_ISSUER is required to pin the token issuer.")
            if not self.resolved_entra_jwks_url:
                problems.append("ENTRA_TENANT_ID or ENTRA_JWKS_URL is required to fetch signing keys.")
            if any(algorithm.startswith("HS") for algorithm in self.entra_allowed_algorithms):
                problems.append(
                    "ENTRA_ALLOWED_ALGORITHMS must not contain a symmetric (HS*) algorithm: a JWKS "
                    "public key would then double as a signing key."
                )
            if "NONE" in self.entra_allowed_algorithms:
                problems.append("ENTRA_ALLOWED_ALGORITHMS must not contain 'none'.")
        if self.allow_testing_lane:
            problems.append(
                "ALLOW_TESTING_LANE is on outside LOCAL; transcribed fixture data could be published."
            )
        if self.database_url.startswith("sqlite"):
            problems.append(
                "DATABASE_URL points at SQLite; a deployed environment must use the MySQL service "
                "so migrations, concurrency and durability match what was tested."
            )
        problems.extend(self._storage_problems())
        problems.extend(self.translation_problems())
        return problems

    def translation_problems(self) -> list[str]:
        if self.translation_provider == "DISABLED":
            return []
        problems = []
        if self.translation_provider != "OPENAI_COMPATIBLE":
            problems.append("TRANSLATION_PROVIDER must be DISABLED or OPENAI_COMPATIBLE.")
        try:
            endpoint = urlsplit(self.translation_base_url)
            valid = endpoint.scheme == "https" and bool(endpoint.hostname) and not (endpoint.username or endpoint.password or endpoint.query or endpoint.fragment)
        except ValueError:
            valid = False
        if not valid:
            problems.append("TRANSLATION_BASE_URL must be an approved HTTPS base URL without credentials or query parameters.")
        if not self.translation_model.strip() or len(self.translation_model) > 255:
            problems.append("TRANSLATION_MODEL requires 1 to 255 characters.")
        if not self.translation_api_key.strip():
            problems.append("TRANSLATION_API_KEY is required from the secret store.")
        if not 1 <= self.translation_timeout_seconds <= 60:
            problems.append("TRANSLATION_TIMEOUT_SECONDS must be between 1 and 60.")
        if not 1 <= self.translation_max_characters <= 50000:
            problems.append("TRANSLATION_MAX_CHARACTERS must be between 1 and 50000.")
        if not 256 <= self.translation_max_tokens <= 32000:
            problems.append("TRANSLATION_MAX_TOKENS must be between 256 and 32000.")
        return problems

    def _storage_problems(self) -> list[str]:
        """Why the artifact store would lose or fail to serve a rendered report.

        The deployment target has no persistent volume, so container-local disk is not storage:
        the artifact disappears at the next restart, and a second replica cannot serve a download
        the first one produced. This is the same class of refusal as SQLite.
        """
        if self.storage_backend not in SUPPORTED_STORAGE_BACKENDS:
            return [
                f"STORAGE_BACKEND={self.storage_backend!r} is not a backend anything implements "
                f"(supported: {', '.join(SUPPORTED_STORAGE_BACKENDS)})."
            ]
        if self.storage_backend == "LOCAL":
            return [
                "STORAGE_BACKEND=LOCAL keeps rendered artifacts on container-local disk. The "
                "deployment provides no persistent volume, so every artifact is lost on restart "
                "and a second replica cannot serve one the first produced. Set STORAGE_BACKEND=S3 "
                "and S3_BUCKET to the approved object store."
            ]
        problems = []
        if not self.s3_bucket:
            problems.append("S3_BUCKET is required when STORAGE_BACKEND=S3; there is nowhere to write.")
        if not self.s3_endpoint_url and not self.s3_region:
            problems.append(
                "S3_REGION or S3_ENDPOINT_URL is required so the client knows which endpoint to "
                "address and which region to sign for."
            )
        return problems


settings = Settings()
