"""Read-only adapter for CSOP data-warehouse product and benchmark period returns."""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from datetime import date, datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import Engine, URL, create_engine, event, inspect, text
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings


CLASS_MASTER = "view_ads_busi_product_fundinfo_class_f_p"
FUND_RETURNS = "view_ads_busi_performance_class_returns_f_p"
INDEX_RETURNS = "view_ads_busi_performance_index_returns_f_p"
INDEX_CONSTITUENTS = "view_ads_busi_market_index_constituent_price_daily_f_p"
RETURN_COLUMNS = {
    "return_1m": "returns_l1m",
    "return_3m": "returns_l3m",
    "return_6m": "returns_l6m",
    "return_ytd": "returns_ytd",
}
REQUIRED_COLUMNS = {
    "class_master": {"class_id", "tradar_code", "fund_name_en", "class_name", "class_type", "ticker", "index_ticker"},
    "fund_returns": {"trade_date", "tradar_code", "class_id", "class_name", *RETURN_COLUMNS.values()},
    "index_returns": {"trade_date", "tradar_code", "class_id", "index_ticker", *RETURN_COLUMNS.values()},
    "index_constituents": {
        "trade_date", "index_code", "stock_code", "stock_name", "stock_name_eng", "ccy",
        "index_weight", "close_price", "industry_code", "industry_code2", "industry_code3", "sector",
    },
}
_VIEW_NAME = re.compile(r"^[A-Za-z0-9_]+$")
_MATERIALIZE_LOCK = threading.Lock()


class DataWarehouseProviderError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 503, *, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.retryable = retryable


def _view_names() -> dict[str, str]:
    views = {
        "class_master": settings.datawarehouse_class_master_view,
        "fund_returns": settings.datawarehouse_fund_returns_view,
        "index_returns": settings.datawarehouse_index_returns_view,
        "index_constituents": settings.datawarehouse_constituents_view,
    }
    invalid = sorted(name for name in views.values() if not _VIEW_NAME.fullmatch(name))
    if invalid:
        raise DataWarehouseProviderError(
            "DATAWAREHOUSE_VIEW_NAME_INVALID",
            "A configured data-warehouse view name is not a permitted SQL identifier.",
        )
    return views


def _mysql_configuration() -> dict[str, Any] | None:
    values = {
        "host": settings.datawarehouse_mysql_host,
        "database": settings.datawarehouse_mysql_database,
        "username": settings.datawarehouse_mysql_username,
        "password": settings.datawarehouse_mysql_password,
    }
    if not any(values.values()):
        return None
    missing = sorted(key for key, value in values.items() if not value)
    if missing:
        raise DataWarehouseProviderError(
            "DATAWAREHOUSE_MYSQL_CONFIG_INCOMPLETE",
            f"The CDB MySQL configuration is missing: {', '.join(missing)}.",
        )
    ssl_ca = settings.datawarehouse_mysql_ssl_ca
    if ssl_ca and not ssl_ca.is_file():
        raise DataWarehouseProviderError(
            "DATAWAREHOUSE_MYSQL_SSL_CA_NOT_FOUND",
            "The configured CDB MySQL CA certificate is not available.",
        )
    return {
        **values,
        "port": settings.datawarehouse_mysql_port,
        "ssl_ca": str(ssl_ca.resolve()) if ssl_ca else None,
        "ssl_verify_identity": settings.datawarehouse_mysql_ssl_verify_identity,
        "timeout_seconds": settings.datawarehouse_timeout_seconds,
    }


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
def _sqlite_engine(path: str) -> Engine:
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


@lru_cache(maxsize=4)
def _mysql_engine(
    host: str,
    port: int,
    database: str,
    username: str,
    password: str,
    timeout_seconds: float,
    ssl_ca: str | None,
    ssl_verify_identity: bool,
) -> Engine:
    ssl_options: dict[str, Any] = {"check_hostname": ssl_verify_identity}
    if ssl_ca:
        ssl_options["ca"] = ssl_ca
    timeout = max(1, int(round(timeout_seconds)))
    engine = create_engine(
        URL.create(
            "mysql+pymysql",
            username=username,
            password=password,
            host=host,
            port=port,
            database=database,
        ),
        connect_args={
            "charset": "utf8mb4",
            "connect_timeout": timeout,
            "read_timeout": timeout,
            "write_timeout": timeout,
            "ssl": ssl_options,
        },
        pool_pre_ping=True,
        pool_recycle=300,
        pool_timeout=timeout_seconds,
    )

    @event.listens_for(engine, "connect")
    def configure_read_only(dbapi_connection, connection_record) -> None:
        del connection_record
        with dbapi_connection.cursor() as cursor:
            cursor.execute("SET SESSION TRANSACTION READ ONLY")
            cursor.execute(f"SET SESSION MAX_EXECUTION_TIME = {max(1000, timeout * 1000)}")

    return engine


def _data_source(views: dict[str, str]) -> tuple[Engine, dict[str, Any]]:
    mysql = _mysql_configuration()
    if mysql:
        engine = _mysql_engine(
            str(mysql["host"]),
            int(mysql["port"]),
            str(mysql["database"]),
            str(mysql["username"]),
            str(mysql["password"]),
            float(mysql["timeout_seconds"]),
            mysql["ssl_ca"],
            bool(mysql["ssl_verify_identity"]),
        )
        return engine, {
            "source_type": "CDB_MYSQL",
            "source_system": "CSOP_CDB_MYSQL",
            "source_name": "CSOP Data Warehouse",
            "source_object": (
                f"{mysql['database']}#"
                f"{views['fund_returns']}+{views['index_returns']}"
            ),
            "file_checksum": None,
        }

    path = _materialize_snapshot()
    stat = path.stat()
    file_checksum = _file_checksum(str(path.resolve()), stat.st_size, stat.st_mtime_ns)
    return _sqlite_engine(str(path.resolve())), {
        "source_type": "DATAWAREHOUSE_SQLITE",
        "source_system": "CSOP_DATAWAREHOUSE_SNAPSHOT",
        "source_name": "CSOP Data Warehouse",
        "source_object": f"{path.name}#{views['fund_returns']}+{views['index_returns']}",
        "file_checksum": file_checksum,
    }


def _validate_schema(
    connection,
    views: dict[str, str],
    roles: tuple[str, ...] = ("class_master", "fund_returns", "index_returns"),
) -> None:
    schema = inspect(connection)
    for role in roles:
        required = REQUIRED_COLUMNS[role]
        table_name = views[role]
        actual = {str(column["name"]) for column in schema.get_columns(table_name)}
        missing = sorted(required - actual)
        if missing:
            raise DataWarehouseProviderError(
                "DATAWAREHOUSE_SCHEMA_MISMATCH",
                f"The CSOP data warehouse is missing fields in {table_name}: {', '.join(missing)}.",
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


def _security_code(raw: Any) -> str:
    token = str(raw or "").strip().split()[0]
    digits = re.sub(r"\D", "", token)
    return digits.lstrip("0") or "0"


def _clean_text(raw: Any) -> str | None:
    value = str(raw or "").strip()
    return value if value and "\ufffd" not in value else None


def _hsics_codes(record: dict[str, Any]) -> dict[str, str | None]:
    industry = _clean_text(record.get("industry_code"))
    sector = _clean_text(record.get("industry_code2")) or _clean_text(record.get("sector"))
    subsector = _clean_text(record.get("industry_code3"))
    if not industry and sector and re.fullmatch(r"\d{4}", sector):
        industry = sector[:2]
    return {
        "hsics_industry": industry,
        "hsics_sector": sector,
        "hsics_subsector": subsector,
    }


def load_index_constituents(
    *,
    index_code: str,
    report_date: date,
    effective_as_of: date | None = None,
) -> dict[str, Any]:
    """Load the report-month HSTECH identity set used as the input to FMP returns.

    The Page 02 effective date is supplied when available.  This keeps the query on an exact CDB
    partition and ensures the identity and return tables use one common report observation date.
    """
    views = _view_names()
    engine, source = _data_source(views)
    requested_date = effective_as_of or report_date
    if requested_date > report_date or requested_date.strftime("%Y-%m") != report_date.strftime("%Y-%m"):
        raise DataWarehouseProviderError(
            "DATAWAREHOUSE_CONSTITUENT_DATE_INVALID",
            "The CDB constituent observation must fall within the selected report month.",
            422,
        )
    try:
        with engine.connect() as connection:
            _validate_schema(connection, views, ("index_constituents",))
            rows = list(connection.execute(text(f"""
                SELECT
                    trade_date, index_code, stock_code, stock_name, stock_name_eng, ccy,
                    index_weight, close_price, industry_code, industry_code2, industry_code3, sector
                FROM {views['index_constituents']}
                WHERE trade_date = :trade_date
                  AND index_code = :index_code
                ORDER BY index_weight DESC, stock_code
            """), {
                "trade_date": requested_date.isoformat(),
                "index_code": index_code,
            }).mappings())
    except DataWarehouseProviderError:
        raise
    except SQLAlchemyError as error:
        raise DataWarehouseProviderError(
            "DATAWAREHOUSE_CONSTITUENTS_QUERY_FAILED",
            "Index constituents could not be queried from the CSOP data warehouse.",
        ) from error

    if not rows:
        raise DataWarehouseProviderError(
            "DATAWAREHOUSE_CONSTITUENTS_NOT_FOUND",
            f"The CDB contains no {index_code} constituent snapshot for {requested_date.isoformat()}.",
            422,
        )
    constituents: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in rows:
        code = _security_code(record["stock_code"])
        if code in seen:
            raise DataWarehouseProviderError(
                "DATAWAREHOUSE_CONSTITUENTS_DUPLICATE",
                f"The CDB constituent snapshot contains duplicate security {code}.",
                422,
            )
        seen.add(code)
        constituents.append({
            "security_code": code,
            "ticker": f"{code.zfill(4)}.HK",
            "name_en": _clean_text(record["stock_name_eng"]) or code,
            "name_zh_hant": _clean_text(record["stock_name"]) or "",
            "close_price": None if record["close_price"] is None else str(record["close_price"]),
            "currency": str(record["ccy"] or "").strip().upper(),
            "weight": None if record["index_weight"] is None else str(record["index_weight"]),
            "as_of_date": str(record["trade_date"]),
            "source_codes": _hsics_codes(dict(record)),
        })

    payload = {
        "constituents": constituents,
        "constituent_index_code": index_code,
        "effective_as_of": requested_date.isoformat(),
    }
    serialized = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    payload_checksum = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    metadata = {
        "source_type": source["source_type"],
        "source_name": source["source_name"],
        "source_object": f"{source['source_object'].split('#', 1)[0]}#{views['index_constituents']}",
        "row_count": len(constituents),
        "checksum": payload_checksum,
        "mapping_version": "cdb-index-constituents-v1",
        "lineage": {
            "source_system": source["source_system"],
            "source_table": views["index_constituents"],
            "source_record_keys": [
                f"{index_code}:{requested_date.isoformat()}:{row['security_code']}"
                for row in constituents
            ],
            "requested_report_date": report_date.isoformat(),
            "effective_as_of": requested_date.isoformat(),
            "weight_unit": "RATIO",
            "extracted_at": datetime.now(timezone.utc).isoformat(),
        },
    }
    return {
        **payload,
        "datasets": {"index_constituents": metadata},
        "source_checksum": payload_checksum,
        "_findings": [],
    }


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
    views = _view_names()
    engine, source = _data_source(views)
    expected_ticker = _ticker_token(fund_ticker)
    benchmark_prefix = benchmark_instrument_code.strip().upper()
    history_start = _month_floor(report_date, month_count - 1)
    try:
        with engine.connect() as connection:
            _validate_schema(connection, views)
            candidates = list(connection.execute(text(f"""
                SELECT class_id, tradar_code, fund_name_en, class_name, class_type, ticker, index_ticker
                FROM {views['class_master']}
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
            query_parameters = {
                "class_id": share_class["class_id"],
                "tradar_code": share_class["tradar_code"],
                "history_start": history_start.isoformat(),
                "report_date": report_date.isoformat(),
                "benchmark_like": f"{benchmark_prefix}%",
            }
            fund_rows = list(connection.execute(text(f"""
                SELECT
                    trade_date, tradar_code, class_id, class_name,
                    returns_l1m AS fund_returns_l1m,
                    returns_l3m AS fund_returns_l3m,
                    returns_l6m AS fund_returns_l6m,
                    returns_ytd AS fund_returns_ytd
                FROM {views['fund_returns']}
                WHERE class_id = :class_id
                  AND tradar_code = :tradar_code
                  AND trade_date BETWEEN :history_start AND :report_date
                ORDER BY trade_date
            """), query_parameters).mappings())
            index_rows = list(connection.execute(text(f"""
                SELECT
                    trade_date, tradar_code, class_id, index_ticker,
                    returns_l1m AS index_returns_l1m,
                    returns_l3m AS index_returns_l3m,
                    returns_l6m AS index_returns_l6m,
                    returns_ytd AS index_returns_ytd
                FROM {views['index_returns']}
                WHERE class_id = :class_id
                  AND tradar_code = :tradar_code
                  AND UPPER(index_ticker) LIKE :benchmark_like
                  AND trade_date BETWEEN :history_start AND :report_date
                ORDER BY trade_date
            """), query_parameters).mappings())
            index_by_key = {
                (row["tradar_code"], row["class_id"], row["trade_date"]): dict(row)
                for row in index_rows
            }
            source_rows = []
            for fund_row in fund_rows:
                key = (fund_row["tradar_code"], fund_row["class_id"], fund_row["trade_date"])
                index_row = index_by_key.get(key)
                if index_row:
                    source_rows.append({**dict(fund_row), **index_row})
    except DataWarehouseProviderError:
        raise
    except SQLAlchemyError as error:
        raise DataWarehouseProviderError(
            "DATAWAREHOUSE_QUERY_FAILED",
            "Historical Performance could not be queried from the CSOP data warehouse.",
        ) from error

    comparable = [
        dict(row)
        for row in source_rows
        if row["index_ticker"] and str(row["index_ticker"]).upper().startswith(benchmark_prefix)
    ]
    if not comparable:
        raise DataWarehouseProviderError(
            "DATAWAREHOUSE_PERFORMANCE_NOT_FOUND",
            f"The configured data source maps {fund_ticker} to {share_class['tradar_code']} / {share_class['class_id']}, "
            f"but contains no product and {benchmark_prefix} benchmark return rows through {report_date.isoformat()}.",
            422,
        )
    by_month: dict[str, dict[str, Any]] = {}
    for row in comparable:
        by_month[str(row["trade_date"])[:7]] = row
    requested_report_month = report_date.strftime("%Y-%m")
    if requested_report_month not in by_month:
        latest_available_month = max(by_month)
        raise DataWarehouseProviderError(
            "DATAWAREHOUSE_REPORT_MONTH_NOT_FOUND",
            f"The configured data source contains no common {fund_ticker} and {benchmark_prefix} return row "
            f"for the selected report month {requested_report_month}; the latest available month not later "
            f"than the report date is {latest_available_month}.",
            422,
        )
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
        "requested_report_month": requested_report_month,
        "effective_as_of": current["effective_as_of"],
        "source_name": source["source_name"],
        "source_tables": [views["fund_returns"], views["index_returns"]],
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
    payload_checksum = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    source_checksum = source["file_checksum"] or payload_checksum
    metadata = {
        "source_type": source["source_type"],
        "source_object": source["source_object"],
        "checksum": payload_checksum,
        "row_count": len(current["rows"]),
        "lineage": {
            "source_system": source["source_system"],
            "source_checksum": source_checksum,
            "source_tables": [views["fund_returns"], views["index_returns"]],
            "source_record_keys": [
                f"{share_class['tradar_code']}:{share_class['class_id']}:{observation['effective_as_of']}"
                for observation in observations
            ],
            "query_window": {"from": history_start.isoformat(), "to": report_date.isoformat()},
            "source_field_map": RETURN_COLUMNS,
            "extracted_at": datetime.now(timezone.utc).isoformat(),
        },
    }
    return {
        "historical_performance": payload,
        "datasets": {"historical_performance": metadata},
        "source_checksum": source_checksum,
    }
