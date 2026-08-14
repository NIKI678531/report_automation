"""Read-only adapter for CSOP data-warehouse product and benchmark period returns."""

from __future__ import annotations

import hashlib
import json
import os
import threading
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings


CLASS_MASTER = "view_ads_busi_product_fundinfo_class_f_p"
FUND_RETURNS = "view_ads_busi_performance_class_returns_f_p"
INDEX_RETURNS = "view_ads_busi_performance_index_returns_f_p"
RETURN_COLUMNS = {
    "return_1m": "returns_l1m",
    "return_3m": "returns_l3m",
    "return_6m": "returns_l6m",
    "return_ytd": "returns_ytd",
}
REQUIRED_COLUMNS = {
    CLASS_MASTER: {"class_id", "tradar_code", "fund_name_en", "class_name", "class_type", "ticker", "index_ticker"},
    FUND_RETURNS: {"trade_date", "tradar_code", "class_id", "class_name", *RETURN_COLUMNS.values()},
    INDEX_RETURNS: {"trade_date", "class_id", "index_ticker", *RETURN_COLUMNS.values()},
}
_MATERIALIZE_LOCK = threading.Lock()


class DataWarehouseProviderError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 503, *, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.retryable = retryable


@lru_cache(maxsize=4)
def _file_checksum(path: str, size: int, modified_ns: int) -> str:
    del size, modified_ns
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_file(path: Path) -> None:
    if not path.is_file():
        raise DataWarehouseProviderError(
            "DATAWAREHOUSE_NOT_CONFIGURED",
            "The CSOP data-warehouse SQLite snapshot is not available in this environment.",
        )
    expected = (settings.datawarehouse_sqlite_sha256 or "").strip().lower()
    if expected:
        stat = path.stat()
        actual = _file_checksum(str(path.resolve()), stat.st_size, stat.st_mtime_ns)
        if actual != expected:
            raise DataWarehouseProviderError(
                "DATAWAREHOUSE_CHECKSUM_MISMATCH",
                "The CSOP data-warehouse snapshot failed its integrity check.",
            )


def _materialize_snapshot(client: httpx.Client | None = None) -> Path:
    local_path = settings.datawarehouse_sqlite_path
    if local_path and local_path.expanduser().is_file():
        path = local_path.expanduser()
        _verify_file(path)
        return path
    object_url = settings.datawarehouse_object_url
    expected = (settings.datawarehouse_sqlite_sha256 or "").strip().lower()
    if not object_url or not expected:
        raise DataWarehouseProviderError(
            "DATAWAREHOUSE_NOT_CONFIGURED",
            "Configure DATAWAREHOUSE_SQLITE_PATH for local development or a checksummed TOS object URL for deployment.",
        )
    cache_root = settings.datawarehouse_cache_dir.expanduser()
    destination = cache_root / f"performance-{expected[:16]}.sqlite"
    with _MATERIALIZE_LOCK:
        if destination.is_file():
            _verify_file(destination)
            return destination
        cache_root.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(".part")
        temporary.unlink(missing_ok=True)
        digest = hashlib.sha256()
        size = 0
        owns_client = client is None
        http_client = client or httpx.Client(
            timeout=settings.datawarehouse_timeout_seconds,
            follow_redirects=True,
        )
        try:
            with http_client.stream("GET", object_url) as response:
                response.raise_for_status()
                with temporary.open("xb") as handle:
                    for chunk in response.iter_bytes(1024 * 1024):
                        size += len(chunk)
                        if size > settings.datawarehouse_max_bytes:
                            raise DataWarehouseProviderError(
                                "DATAWAREHOUSE_TOO_LARGE",
                                "The CSOP data-warehouse snapshot exceeds the configured size limit.",
                            )
                        digest.update(chunk)
                        handle.write(chunk)
            if digest.hexdigest() != expected:
                raise DataWarehouseProviderError(
                    "DATAWAREHOUSE_CHECKSUM_MISMATCH",
                    "The downloaded CSOP data-warehouse snapshot failed its integrity check.",
                )
            os.replace(temporary, destination)
            destination.chmod(0o444)
            return destination
        except DataWarehouseProviderError:
            temporary.unlink(missing_ok=True)
            raise
        except (httpx.HTTPError, OSError) as error:
            temporary.unlink(missing_ok=True)
            raise DataWarehouseProviderError(
                "DATAWAREHOUSE_DOWNLOAD_FAILED",
                "The CSOP data-warehouse snapshot could not be downloaded.",
                retryable=True,
            ) from error
        finally:
            if owns_client:
                http_client.close()


@lru_cache(maxsize=4)
def _engine(path: str) -> Engine:
    database_uri = f"file:{Path(path).resolve().as_posix()}?mode=ro"
    engine = create_engine(
        f"sqlite+pysqlite:///{database_uri}&uri=true",
        connect_args={"timeout": settings.datawarehouse_timeout_seconds},
        pool_pre_ping=True,
    )

    @event.listens_for(engine, "connect")
    def configure_read_only(dbapi_connection, connection_record) -> None:
        del connection_record
        dbapi_connection.execute("PRAGMA query_only=ON")

    return engine


def _validate_schema(connection) -> None:
    for table_name, required in REQUIRED_COLUMNS.items():
        actual = {
            str(row["name"])
            for row in connection.execute(text(f'PRAGMA table_info("{table_name}")')).mappings()
        }
        missing = sorted(required - actual)
        if missing:
            raise DataWarehouseProviderError(
                "DATAWAREHOUSE_SCHEMA_MISMATCH",
                f"The CSOP data-warehouse snapshot is missing fields in {table_name}: {', '.join(missing)}.",
            )


def _ticker_token(ticker: str) -> str:
    normalized = ticker.strip().upper().replace(".", " ")
    return normalized if normalized.endswith(" EQUITY") else f"{normalized} EQUITY"


def _ticker_matches(raw: Any, expected: str) -> bool:
    return expected in {item.strip().upper() for item in str(raw or "").split("|")}


def _month_floor(value: date, months_back: int) -> date:
    month_index = value.year * 12 + value.month - 1 - months_back
    year, zero_based_month = divmod(month_index, 12)
    return date(year, zero_based_month + 1, 1)


def _display_month(value: str) -> str:
    parsed = date.fromisoformat(f"{value}-01")
    return parsed.strftime("%B %Y")


def _period_rows(record: dict[str, Any], *, fund_ticker: str, benchmark_name: str) -> list[dict[str, Any]]:
    def leg(role: str, name: str, instrument_code: str, prefix: str) -> dict[str, Any]:
        return {
            "role": role,
            "name": name,
            "instrument_code": instrument_code,
            **{
                output: None if record[f"{prefix}_{source}"] is None else str(record[f"{prefix}_{source}"])
                for output, source in RETURN_COLUMNS.items()
            },
        }

    return [
        leg("FUND", fund_ticker, str(record["tradar_code"]), "fund"),
        leg("BENCHMARK", benchmark_name, str(record["index_ticker"]), "index"),
    ]


def load_historical_performance(
    *,
    fund_ticker: str,
    benchmark_instrument_code: str,
    report_date: date,
    formula_version: str,
    month_count: int = 12,
) -> dict[str, Any]:
    """Return source-supplied 1M/3M/6M/YTD values for the latest date in each report month."""
    if month_count < 1 or month_count > 24:
        raise ValueError("month_count must be between 1 and 24")
    path = _materialize_snapshot()
    stat = path.stat()
    file_checksum = _file_checksum(str(path.resolve()), stat.st_size, stat.st_mtime_ns)
    expected_ticker = _ticker_token(fund_ticker)
    benchmark_prefix = benchmark_instrument_code.strip().upper()
    history_start = _month_floor(report_date, month_count - 1)
    try:
        with _engine(str(path.resolve())).connect() as connection:
            _validate_schema(connection)
            candidates = list(connection.execute(text(f"""
                SELECT class_id, tradar_code, fund_name_en, class_name, class_type, ticker, index_ticker
                FROM {CLASS_MASTER}
                WHERE UPPER(class_type) = 'LISTED'
                  AND LOWER(class_name) NOT LIKE '%unlisted%'
                ORDER BY class_id
            """)).mappings())
            share_classes = [row for row in candidates if _ticker_matches(row["ticker"], expected_ticker)]
            if len(share_classes) != 1:
                raise DataWarehouseProviderError(
                    "DATAWAREHOUSE_FUND_MAPPING_NOT_UNIQUE",
                    f"Expected one listed share class for {fund_ticker}; found {len(share_classes)}.",
                    422,
                )
            share_class = share_classes[0]
            source_rows = list(connection.execute(text(f"""
                SELECT
                    c.trade_date,
                    c.tradar_code,
                    c.class_id,
                    c.class_name,
                    i.index_ticker,
                    c.returns_l1m AS fund_returns_l1m,
                    c.returns_l3m AS fund_returns_l3m,
                    c.returns_l6m AS fund_returns_l6m,
                    c.returns_ytd AS fund_returns_ytd,
                    i.returns_l1m AS index_returns_l1m,
                    i.returns_l3m AS index_returns_l3m,
                    i.returns_l6m AS index_returns_l6m,
                    i.returns_ytd AS index_returns_ytd
                FROM {FUND_RETURNS} c
                LEFT JOIN {INDEX_RETURNS} i
                  ON i.class_id = c.class_id
                 AND i.trade_date = c.trade_date
                WHERE c.class_id = :class_id
                  AND c.trade_date BETWEEN :history_start AND :report_date
                ORDER BY c.trade_date
            """), {
                "class_id": share_class["class_id"],
                "history_start": history_start.isoformat(),
                "report_date": report_date.isoformat(),
            }).mappings())
    except DataWarehouseProviderError:
        raise
    except SQLAlchemyError as error:
        raise DataWarehouseProviderError(
            "DATAWAREHOUSE_QUERY_FAILED",
            "Historical Performance could not be queried from the CSOP data-warehouse snapshot.",
        ) from error

    comparable = [
        dict(row)
        for row in source_rows
        if row["index_ticker"] and str(row["index_ticker"]).upper().startswith(benchmark_prefix)
    ]
    if not comparable:
        raise DataWarehouseProviderError(
            "DATAWAREHOUSE_PERFORMANCE_NOT_FOUND",
            f"The configured snapshot maps {fund_ticker} to {share_class['tradar_code']} / {share_class['class_id']}, "
            f"but contains no product and {benchmark_prefix} benchmark return rows through {report_date.isoformat()}.",
            422,
        )
    by_month: dict[str, dict[str, Any]] = {}
    for row in comparable:
        by_month[str(row["trade_date"])[:7]] = row
    selected = [by_month[key] for key in sorted(by_month, reverse=True)[:month_count]]
    fund_name = str(share_class["fund_name_en"] or fund_ticker)
    benchmark_name = str(selected[0]["index_ticker"])
    observations = [{
        "month": str(row["trade_date"])[:7],
        "month_label": _display_month(str(row["trade_date"])[:7]),
        "effective_as_of": str(row["trade_date"]),
        "rows": _period_rows(
            row,
            fund_ticker=fund_ticker,
            benchmark_name=str(row["index_ticker"]),
        ),
    } for row in selected]
    current = observations[0]
    periods = {
        output: {
            "period_end": current["effective_as_of"],
            "source_field": source,
            "source_period": source.removeprefix("returns_"),
        }
        for output, source in RETURN_COLUMNS.items()
    }
    payload = {
        "rows": current["rows"],
        "periods": periods,
        "monthly_observations": observations,
        "requested_report_month": report_date.strftime("%Y-%m"),
        "effective_as_of": current["effective_as_of"],
        "source_name": "CSOP Data Warehouse",
        "source_tables": [FUND_RETURNS, INDEX_RETURNS],
        "source_mapping": {
            "fund_ticker": fund_ticker,
            "fund_name": fund_name,
            "tradar_code": str(share_class["tradar_code"]),
            "class_id": str(share_class["class_id"]),
            "class_name": str(share_class["class_name"]),
            "benchmark_index_ticker": benchmark_name,
        },
        "calculation_method": "SOURCE_PERIOD_RETURN",
        "formula_version": formula_version,
    }
    serialized = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    metadata = {
        "source_type": "DATAWAREHOUSE_SQLITE",
        "source_object": f"{path.name}#{FUND_RETURNS}+{INDEX_RETURNS}",
        "checksum": hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
        "row_count": len(current["rows"]),
        "lineage": {
            "source_system": "CSOP_DATAWAREHOUSE",
            "sqlite_checksum": file_checksum,
            "source_tables": [FUND_RETURNS, INDEX_RETURNS],
            "source_record_keys": [
                f"{share_class['class_id']}:{observation['effective_as_of']}"
                for observation in observations
            ],
            "query_window": {"from": history_start.isoformat(), "to": report_date.isoformat()},
            "source_field_map": RETURN_COLUMNS,
        },
    }
    return {
        "historical_performance": payload,
        "datasets": {"historical_performance": metadata},
        "source_checksum": file_checksum,
    }
