from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import json
import os
import re
import ssl
import threading
import unicodedata
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from dataclasses import dataclass
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

import httpx
from sqlalchemy import Engine, create_engine, event, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings
from app.integrations.news import NewsProviderError
from app.domain.localization import simplified_to_traditional, traditional_to_simplified


NEWS_REQUIRED_COLUMNS = {
    "news_sources": {"id", "code", "name_en", "name_zh", "report_type"},
    "news_items": {
        "id", "source_id", "url", "title_raw", "summary_raw", "published_at", "fetched_at",
    },
    "news_enrichments": {
        "news_item_id", "title_en", "title_zh", "summary_en", "summary_zh", "category",
        "region", "sentiment", "importance_score", "model",
    },
}
MONTHLY_REQUIRED_COLUMNS = {
    "total_return_series": {
        "id", "instrument_code", "trade_date", "total_return_value", "series_type",
        "currency", "source", "updated_at",
    },
    "fund_kpi_daily": {
        "id", "product_code", "metric_date", "metric_code", "value", "unit", "currency",
        "source", "updated_at",
    },
    "trading_calendar": {
        "id", "market_code", "trade_date", "is_trading_day", "source", "updated_at",
    },
    "index_events": {
        "id", "index_code", "event_type", "announcement_date", "effective_date", "source",
        "updated_at",
    },
}
MONTHLY_TURNOVER_REQUIRED_COLUMNS = {
    "id", "bloomberg_ticker", "calendar_ticker", "month_start", "period_start",
    "period_end", "total_turnover", "trading_days", "average_daily_turnover", "currency",
    "fetched_at",
}
_NON_WORD = re.compile(r"[^0-9A-Za-z\u3400-\u9fff]+")
_LATIN_BOUNDARY = r"0-9A-Z"
_LISTING_SUFFIXES = {"S", "SW", "W"}
_MATERIALIZE_LOCK = threading.Lock()


class DaReportProviderError(NewsProviderError):
    pass


def is_configured() -> bool:
    if settings.da_report_database_url:
        return not settings.da_report_mysql_problems()
    path = settings.da_report_sqlite_path
    return bool(
        (path and path.expanduser().is_file())
        or (settings.da_report_object_url and settings.da_report_sqlite_sha256)
    )


def _normalize_text(value: Any) -> str:
    tokens = _NON_WORD.sub(" ", unicodedata.normalize("NFKC", str(value or "")).upper()).split()
    if tokens and tokens[-1] in _LISTING_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def _contains_alias(text_value: str, alias: str) -> bool:
    if any("\u3400" <= character <= "\u9fff" for character in alias):
        return alias in text_value
    return re.search(
        rf"(?<![{_LATIN_BOUNDARY}]){re.escape(alias)}(?![{_LATIN_BOUNDARY}])",
        text_value,
    ) is not None


def _sqlite_contains_company_alias(text_value: Any, alias: Any) -> int:
    """SQLite scalar used so company matching participates in count and pagination."""
    normalized_alias = _normalize_text(alias)
    if not normalized_alias:
        return 0
    return int(_contains_alias(_normalize_text(text_value), normalized_alias))


def _company_aliases(constituent: dict[str, Any]) -> list[str]:
    source_names = constituent.get("source_names") if isinstance(constituent.get("source_names"), dict) else {}
    name_zh_hant = str(constituent.get("name_zh_hant") or "").strip()
    name_zh_hans = str(constituent.get("name_zh_hans") or "").strip()
    converted_name_zh_hans = traditional_to_simplified(name_zh_hant) if name_zh_hant else ""
    converted_name_zh_hant = simplified_to_traditional(name_zh_hans) if name_zh_hans else ""
    values = (
        constituent.get("report_display_name"),
        constituent.get("name_en"),
        name_zh_hant,
        name_zh_hans,
        converted_name_zh_hans,
        converted_name_zh_hant,
        constituent.get("ticker"),
        *source_names.values(),
    )
    aliases: list[str] = []
    for value in values:
        alias = _normalize_text(value)
        if len(alias) >= 2 and alias not in aliases:
            aliases.append(alias)
    return aliases


def _company_facets(constituents: list[dict[str, Any]]) -> list[dict[str, str | None]]:
    facets: list[dict[str, str | None]] = []
    seen: set[str] = set()
    for row in constituents:
        security_code = str(row.get("security_code") or "").strip()
        if not security_code or security_code in seen:
            continue
        seen.add(security_code)
        name_en = str(row.get("name_en") or row.get("name_zh_hant") or security_code).strip()
        name_zh_hant = str(row.get("name_zh_hant") or "").strip() or None
        name_zh_hans = str(row.get("name_zh_hans") or "").strip() or None
        if name_zh_hans is None and name_zh_hant is not None:
            name_zh_hans = traditional_to_simplified(name_zh_hant) or None
        facets.append({
            "security_code": security_code,
            "ticker": str(row.get("ticker") or "").strip(),
            "name_en": name_en,
            "name_zh_hans": name_zh_hans,
            "name_zh_hant": name_zh_hant,
        })
    return facets


def _constituent_aliases(constituents: list[dict[str, Any]]) -> list[tuple[str, str, str]]:
    aliases: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str]] = set()
    for row in constituents:
        security_code = str(row.get("security_code") or "").strip()
        ticker = str(row.get("ticker") or "").strip().upper()
        if not security_code or not ticker:
            continue
        source_names = row.get("source_names") if isinstance(row.get("source_names"), dict) else {}
        values = (
            row.get("report_display_name"),
            row.get("name_en"),
            row.get("name_zh_hant"),
            row.get("name_zh_hans"),
            simplified_to_traditional(row.get("name_zh_hans")) if row.get("name_zh_hans") else None,
            traditional_to_simplified(row.get("name_zh_hant")) if row.get("name_zh_hant") else None,
            *source_names.values(),
        )
        for value in values:
            alias = _normalize_text(value)
            has_cjk = any("\u3400" <= character <= "\u9fff" for character in alias)
            if not alias or (has_cjk and len(alias) < 2) or (not has_cjk and len(alias) < 4):
                continue
            key = (security_code, alias)
            if key not in seen:
                aliases.append((alias, security_code, ticker))
                seen.add(key)
    return aliases


def _match_title(
    title_en: str | None,
    title_zh: str | None,
    aliases: list[tuple[str, str, str]],
) -> tuple[str, str, str] | None:
    normalized_title = _normalize_text(f"{title_en or ''} {title_zh or ''}")
    matches = [item for item in aliases if _contains_alias(normalized_title, item[0])]
    security_codes = {item[1] for item in matches}
    if len(security_codes) != 1:
        return None
    return sorted(matches, key=lambda item: -len(item[0]))[0]


def _verify_file(path: Path) -> None:
    if not path.is_file():
        raise DaReportProviderError(
            "DA_REPORT_NOT_CONFIGURED",
            "The DA-Report news snapshot is not available in this environment.",
            503,
        )
    expected = (settings.da_report_sqlite_sha256 or "").strip().lower()
    if expected:
        stat = path.stat()
        actual = _file_checksum(str(path.resolve()), stat.st_size, stat.st_mtime_ns)
        if actual != expected:
            raise DaReportProviderError(
                "DA_REPORT_CHECKSUM_MISMATCH",
                "The DA-Report news snapshot failed its integrity check.",
                503,
            )


def _materialize_snapshot(client: httpx.Client | None = None) -> Path:
    local_path = settings.da_report_sqlite_path
    if local_path and local_path.expanduser().is_file():
        path = local_path.expanduser()
        _verify_file(path)
        return path
    object_url = settings.da_report_object_url
    expected = (settings.da_report_sqlite_sha256 or "").strip().lower()
    if not object_url or not expected:
        raise DaReportProviderError(
            "DA_REPORT_NOT_CONFIGURED",
            "The DA-Report news snapshot is not configured in this environment.",
            503,
        )
    cache_root = settings.da_report_cache_dir.expanduser()
    destination = cache_root / f"da-report-{expected[:16]}.sqlite"
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
            timeout=settings.da_report_timeout_seconds,
            follow_redirects=True,
        )
        try:
            with http_client.stream("GET", object_url) as response:
                response.raise_for_status()
                with temporary.open("xb") as handle:
                    for chunk in response.iter_bytes(1024 * 1024):
                        size += len(chunk)
                        if size > settings.da_report_max_bytes:
                            raise DaReportProviderError(
                                "DA_REPORT_TOO_LARGE",
                                "The DA-Report news snapshot exceeds the configured size limit.",
                                503,
                            )
                        digest.update(chunk)
                        handle.write(chunk)
            if digest.hexdigest() != expected:
                raise DaReportProviderError(
                    "DA_REPORT_CHECKSUM_MISMATCH",
                    "The downloaded DA-Report news snapshot failed its integrity check.",
                    503,
                )
            os.replace(temporary, destination)
            destination.chmod(0o444)
            return destination
        except DaReportProviderError:
            temporary.unlink(missing_ok=True)
            raise
        except (httpx.HTTPError, OSError) as error:
            temporary.unlink(missing_ok=True)
            raise DaReportProviderError(
                "DA_REPORT_DOWNLOAD_FAILED",
                "The DA-Report news snapshot could not be downloaded.",
                503,
                retryable=True,
            ) from error
        finally:
            if owns_client:
                http_client.close()


@lru_cache(maxsize=4)
def _file_checksum(path: str, size: int, modified_ns: int) -> str:
    del size, modified_ns
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@lru_cache(maxsize=4)
def _engine(path: str) -> Engine:
    database_uri = f"file:{Path(path).resolve().as_posix()}?mode=ro"
    engine = create_engine(
        f"sqlite+pysqlite:///{database_uri}&uri=true",
        connect_args={"timeout": settings.da_report_timeout_seconds},
        pool_pre_ping=True,
    )

    @event.listens_for(engine, "connect")
    def configure_read_only(dbapi_connection, connection_record) -> None:
        del connection_record
        dbapi_connection.create_function(
            "contains_company_alias",
            2,
            _sqlite_contains_company_alias,
            deterministic=True,
        )
        dbapi_connection.execute("PRAGMA query_only=ON")

    return engine


@lru_cache(maxsize=4)
def _mysql_engine(database_url: str, timeout: int, ssl_ca: str | None, verify_identity: bool) -> Engine:
    tls = ssl.create_default_context(cafile=ssl_ca)
    tls.check_hostname = verify_identity
    if not verify_identity:  # LOCAL test databases may use MySQL's generated CA.
        tls.verify_flags &= ~ssl.VERIFY_X509_STRICT
    engine = create_engine(
        make_url(database_url),
        connect_args={"charset": "utf8mb4", "connect_timeout": timeout, "read_timeout": timeout,
                      "write_timeout": timeout, "ssl": tls},
        pool_pre_ping=True, pool_recycle=300, pool_size=3, max_overflow=2, pool_timeout=timeout,
        isolation_level="REPEATABLE READ", hide_parameters=True,
    )

    @event.listens_for(engine, "connect")
    def configure_read_only(dbapi_connection, connection_record):
        del connection_record
        with dbapi_connection.cursor() as cursor:
            cursor.execute("SET SESSION TRANSACTION READ ONLY")
            cursor.execute(f"SET SESSION MAX_EXECUTION_TIME = {timeout * 1000}")
            cursor.execute("SET SESSION time_zone = '+00:00'")
            # PyMySQL can fall back to plaintext if the server does not offer TLS.
            cursor.execute("SHOW SESSION STATUS LIKE 'Ssl_cipher'")
            if not cursor.fetchone()[1]:
                raise DaReportProviderError("DA_REPORT_TLS_REQUIRED", "DA-Report MySQL requires TLS.", 503)

    return engine


@dataclass(frozen=True)
class _DataSource:
    engine: Engine
    name: str
    file_checksum: str | None = None

    @property
    def source_type(self) -> str:
        return "DA_REPORT_SQLITE" if self.file_checksum else "DA_REPORT_MYSQL"


def _data_source() -> _DataSource:
    # An explicit MySQL source never falls back to a stale local file or object URL on failure.
    if settings.da_report_database_url:
        if settings.da_report_mysql_problems():
            raise DaReportProviderError("DA_REPORT_CONFIGURATION_INVALID", "Check the DA-Report MySQL configuration.", 503)
        try:
            engine = _mysql_engine(
                settings.da_report_database_url, max(1, int(settings.da_report_timeout_seconds)),
                str(settings.da_report_mysql_ssl_ca) if settings.da_report_mysql_ssl_ca else None,
                settings.da_report_mysql_ssl_verify_identity,
            )
        except (SQLAlchemyError, OSError, ValueError):
            raise DaReportProviderError("DA_REPORT_CONFIGURATION_INVALID", "Check the DA-Report MySQL configuration and CA bundle.", 503) from None
        return _DataSource(engine, "DA_REPORT")
    path = _materialize_snapshot()
    stat = path.stat()
    return _DataSource(_engine(str(path.resolve())), path.name,
                       _file_checksum(str(path.resolve()), stat.st_size, stat.st_mtime_ns))


def _table_columns(connection, table_name: str) -> set[str]:
    schema = inspect(connection)
    if not schema.has_table(table_name):
        return set()
    return {str(column["name"]) for column in schema.get_columns(table_name)}


@contextmanager
def _connect_source(source: _DataSource):
    try:
        with source.engine.connect() as connection:
            yield connection
    except (SQLAlchemyError, OSError, ValueError):
        # Do not expose SQL, credentials or connection details through provider errors or traces.
        raise DaReportProviderError("DA_REPORT_UNAVAILABLE", "The DA-Report data source could not be queried.", 503, retryable=True) from None


def _joined_text(source: _DataSource, columns: tuple[str, ...]) -> str:
    parts = [f"COALESCE({column}, '')" for column in columns]
    if source.engine.dialect.name == "mysql":
        return "CONCAT_WS(' ', " + ", ".join(parts) + ")"
    return " || ' ' || ".join(parts)


def _company_predicate(source: _DataSource, title: str, key: str, alias: str, parameters: dict) -> str:
    if source.engine.dialect.name != "mysql":
        parameters[key] = alias
        return f"contains_company_alias({title}, :{key}) = 1"
    # ICU regular expressions replace the SQLite UDF. Parameters keep aliases out of SQL.
    # Include full-width ASCII forms (NFKC in the SQLite implementation), punctuation separators,
    # and Latin token boundaries so NIO does not match 'senior'. Chinese names match substrings.
    normalized = _normalize_text(alias)
    parts = []
    for char in normalized:
        if char == " ":
            parts.append("[^0-9A-Z㐀-鿿０-９Ａ-Ｚａ-ｚ]+")
        elif char.isascii() and char.isalnum():
            parts.append(f"[{char}{chr(ord(char) + 0xFEE0)}]")
        else:
            parts.append(re.escape(char))
    pattern = "".join(parts)
    if not any("\u3400" <= char <= "\u9fff" for char in normalized):
        pattern = "(^|[^0-9A-Z０-９Ａ-Ｚａ-ｚ])" + pattern + "([^0-9A-Z０-９Ａ-Ｚａ-ｚ]|$)"
    parameters[key] = pattern
    return f"REGEXP_LIKE({title}, :{key}, 'i')"


def _source_checksum(source: _DataSource, datasets: dict) -> str:
    if source.file_checksum:
        return source.file_checksum
    encoded = json.dumps({name: metadata["checksum"] for name, metadata in datasets.items()}, sort_keys=True)
    return hashlib.sha256(encoded.encode()).hexdigest()


def _validate_columns(connection, required_columns: dict[str, set[str]], error_code: str) -> None:
    for table_name, required in required_columns.items():
        actual = _table_columns(connection, table_name)
        missing = sorted(required - actual)
        if missing:
            raise DaReportProviderError(
                error_code,
                f"The DA-Report snapshot is missing required fields in {table_name}: {', '.join(missing)}.",
                503,
            )


def _validate_schema(connection) -> None:
    _validate_columns(connection, NEWS_REQUIRED_COLUMNS, "DA_REPORT_SCHEMA_MISMATCH")


def _validate_monthly_schema(connection) -> None:
    _validate_columns(connection, MONTHLY_REQUIRED_COLUMNS, "DA_REPORT_MONTHLY_SCHEMA_MISMATCH")


def _missing_table_columns(connection, table_name: str) -> list[str]:
    actual = _table_columns(connection, table_name)
    return sorted(MONTHLY_REQUIRED_COLUMNS[table_name] - actual)


def _monthly_dataset_metadata(
    source: _DataSource,
    table_name: str,
    rows: list[dict[str, Any]],
    query_window: dict[str, str | None],
) -> dict[str, Any]:
    payload = json.dumps(rows, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return {
        "source_type": source.source_type,
        "source_object": f"{source.name}#{table_name}",
        "checksum": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        "row_count": len(rows),
        "lineage": {
            "source_system": source.source_type,
            # Retrieval time belongs to the enclosing snapshot/audit. Keep content metadata stable
            # so refreshing unchanged MySQL rows does not create a new snapshot just for the clock.
            **({"sqlite_checksum": source.file_checksum} if source.file_checksum else {"read_consistency": "REPEATABLE_READ"}),
            "source_table": table_name,
            "source_record_ids": [row["_source_id"] for row in rows],
            "query_window": query_window,
        },
    }


def load_monthly_data(
    *,
    product_code: str,
    fund_instrument_code: str,
    benchmark_instrument_code: str,
    trading_calendar_code: str,
    constituent_index_code: str,
    report_date: date,
) -> dict[str, Any]:
    source = _data_source()
    history_start = date(report_date.year - 1, 1, 1)
    month_start = report_date.replace(day=1)
    provider_findings: list[dict[str, Any]] = []
    with _connect_source(source) as connection:
        # Historical performance is independently releasable. Missing KPI/calendar/event tables
        # keep the report pending, but must not hide a complete official FUND/BENCHMARK series.
        _validate_columns(
            connection,
            {"total_return_series": MONTHLY_REQUIRED_COLUMNS["total_return_series"]},
            "DA_REPORT_MONTHLY_SCHEMA_MISMATCH",
        )
        optional_ready: dict[str, bool] = {}
        for table_name in ("fund_kpi_daily", "trading_calendar", "index_events"):
            missing_columns = _missing_table_columns(connection, table_name)
            optional_ready[table_name] = not missing_columns
            if missing_columns:
                provider_findings.append({
                    "check_id": f"DA_REPORT_{table_name.upper()}_SCHEMA_MISMATCH",
                    "error_code": f"DA_REPORT_{table_name.upper()}_SCHEMA_MISMATCH",
                    "severity": "WARNING" if table_name == "index_events" else "BLOCKING",
                    "status": "FAILED",
                    "message": f"DA-Report is missing required fields in {table_name}: {', '.join(missing_columns)}.",
                    "actual": {"missing_columns": missing_columns},
                    "threshold": {"required_columns": sorted(MONTHLY_REQUIRED_COLUMNS[table_name])},
                    "fix_hint": f"Publish {table_name} in the configured DA-Report source; Historical Performance remains available.",
                })
        total_return_rows = list(connection.execute(text("""
            SELECT id, instrument_code, trade_date, total_return_value, series_type, currency, source, updated_at
            FROM total_return_series
            WHERE instrument_code IN (:fund_code, :benchmark_code)
              AND trade_date BETWEEN :history_start AND :report_date
            ORDER BY trade_date, instrument_code
        """), {
            "fund_code": fund_instrument_code,
            "benchmark_code": benchmark_instrument_code,
            "history_start": history_start.isoformat(),
            "report_date": report_date.isoformat(),
        }).mappings())
        kpi_rows = list(connection.execute(text("""
            SELECT id, product_code, metric_date, metric_code, value, unit, currency, source
            FROM fund_kpi_daily
            WHERE product_code = :product_code
              AND metric_date BETWEEN :month_start AND :report_date
            ORDER BY metric_date, metric_code
        """), {
            "product_code": product_code,
            "month_start": month_start.isoformat(),
            "report_date": report_date.isoformat(),
        }).mappings()) if optional_ready["fund_kpi_daily"] else []
        calendar_rows = list(connection.execute(text("""
            SELECT id, market_code, trade_date, is_trading_day, source
            FROM trading_calendar
            WHERE market_code = :market_code
              AND trade_date BETWEEN :month_start AND :report_date
            ORDER BY trade_date
        """), {
            "market_code": trading_calendar_code,
            "month_start": month_start.isoformat(),
            "report_date": report_date.isoformat(),
        }).mappings()) if optional_ready["trading_calendar"] else []
        event_rows = list(connection.execute(text("""
            SELECT id, index_code, event_type, announcement_date, effective_date, source
            FROM index_events
            WHERE index_code = :index_code AND effective_date > :report_date
            ORDER BY effective_date
        """), {
            "index_code": constituent_index_code,
            "report_date": report_date.isoformat(),
        }).mappings()) if optional_ready["index_events"] else []

    roles = {
        fund_instrument_code: "FUND",
        benchmark_instrument_code: "BENCHMARK",
    }
    series = [{
        "_source_id": int(row["id"]),
        "instrument_role": roles.get(str(row["instrument_code"]), ""),
        "instrument_code": str(row["instrument_code"]),
        "trade_date": str(row["trade_date"]),
        "total_return_value": str(row["total_return_value"]),
        "series_type": str(row["series_type"]),
        "currency": str(row["currency"]).upper(),
        "source": str(row["source"]),
        "source_updated_at": str(row["updated_at"]),
    } for row in total_return_rows]
    series_roles = {row["instrument_role"] for row in series}
    currencies = {row["currency"] for row in series}
    series_keys = {(row["instrument_role"], row["trade_date"]) for row in series}
    try:
        positive_series = all(Decimal(row["total_return_value"]) > 0 for row in series)
    except InvalidOperation:
        positive_series = False
    if series_roles != {"FUND", "BENCHMARK"} or any(
        row["series_type"].replace("_", " ").upper() != "TOTAL RETURN" for row in series
    ) or len(currencies) != 1 or len(series_keys) != len(series) or not positive_series:
        raise DaReportProviderError(
            "DA_REPORT_TOTAL_RETURN_INCOMPLETE",
            "The DA-Report snapshot does not contain comparable official FUND and BENCHMARK Total Return series.",
            422,
        )

    fund_kpis = [{
        "_source_id": int(row["id"]),
        "product_code": str(row["product_code"]),
        "metric_date": str(row["metric_date"]),
        "metric_code": str(row["metric_code"]).upper(),
        "value": str(row["value"]),
        "unit": str(row["unit"]),
        "currency": str(row["currency"]).upper(),
        "source": str(row["source"]),
    } for row in kpi_rows]
    aum_rows = [row for row in fund_kpis if row["metric_code"] == "AUM" and row["metric_date"] == report_date.isoformat()]
    turnover_rows = [row for row in fund_kpis if row["metric_code"] == "DAILY_TURNOVER"]
    kpi_keys = {(row["metric_code"], row["metric_date"]) for row in fund_kpis}
    try:
        nonnegative_kpis = all(Decimal(row["value"]) >= 0 for row in fund_kpis)
    except InvalidOperation:
        nonnegative_kpis = False
    kpi_invalid = (
        len(aum_rows) != 1
        or not turnover_rows
        or len(kpi_keys) != len(fund_kpis)
        or not nonnegative_kpis
        or any(row["metric_code"] not in {"AUM", "DAILY_TURNOVER"} for row in fund_kpis)
        or any(not row["unit"] or not row["currency"] for row in fund_kpis)
    )
    if optional_ready["fund_kpi_daily"] and kpi_invalid:
        provider_findings.append({
            "check_id": "DA_REPORT_FUND_KPI_INCOMPLETE", "error_code": "DA_REPORT_FUND_KPI_INCOMPLETE",
            "severity": "BLOCKING", "status": "FAILED",
            "message": "The DA-Report snapshot requires one report-date AUM row and report-month daily turnover rows.",
            "actual": {"rows": len(fund_kpis)}, "threshold": "One report-date AUM and report-month turnover rows",
            "fix_hint": "Backfill the official fund KPI rows in DA-Report and publish the updated source.",
        })

    calendar = [{
        "_source_id": int(row["id"]),
        "market": str(row["market_code"]),
        "date": str(row["trade_date"]),
        "is_trading_day": bool(row["is_trading_day"]),
        "source": str(row["source"]),
    } for row in calendar_rows]
    calendar_valid = len({row["date"] for row in calendar}) == len(calendar) and any(row["is_trading_day"] for row in calendar)
    if optional_ready["trading_calendar"] and not calendar_valid:
        provider_findings.append({
            "check_id": "DA_REPORT_TRADING_CALENDAR_INCOMPLETE", "error_code": "DA_REPORT_TRADING_CALENDAR_INCOMPLETE",
            "severity": "BLOCKING", "status": "FAILED",
            "message": "The DA-Report snapshot contains no report-month trading days for this product.",
            "actual": {"rows": len(calendar)}, "threshold": "At least one report-month trading day",
            "fix_hint": "Backfill the official market calendar in DA-Report and publish the updated source.",
        })

    index_events = [{
        "_source_id": int(row["id"]),
        "index_code": str(row["index_code"]),
        "event_type": str(row["event_type"]).upper(),
        "announcement_date": str(row["announcement_date"]) if row["announcement_date"] else None,
        "effective_date": str(row["effective_date"]),
        "source": str(row["source"]),
    } for row in event_rows]
    datasets = {
        "total_return_series": _monthly_dataset_metadata(
            source, "total_return_series", series,
            {"from": history_start.isoformat(), "to": report_date.isoformat()},
        ),
    }
    if optional_ready["fund_kpi_daily"] and not kpi_invalid:
        datasets["fund_kpi_daily"] = _monthly_dataset_metadata(
            source, "fund_kpi_daily", fund_kpis,
            {"from": month_start.isoformat(), "to": report_date.isoformat()},
        )
    if optional_ready["trading_calendar"] and calendar_valid:
        datasets["trading_calendar"] = _monthly_dataset_metadata(
            source, "trading_calendar", calendar,
            {"from": month_start.isoformat(), "to": report_date.isoformat()},
        )
    if optional_ready["index_events"]:
        datasets["index_events"] = _monthly_dataset_metadata(
            source, "index_events", index_events,
            {"from": report_date.isoformat(), "to": None},
        )
    for rows in (series, fund_kpis, calendar, index_events):
        for row in rows:
            row.pop("_source_id", None)
    return {
        "total_return_series": series,
        "fund_kpis": fund_kpis,
        "trading_calendar": calendar,
        "index_events": index_events,
        "datasets": datasets,
        "source_checksum": _source_checksum(source, datasets),
        "_findings": provider_findings,
    }


def _bloomberg_equity_ticker(product_ticker: str) -> str:
    """Translate the catalog's listed ticker to the explicit Bloomberg equity identifier."""
    normalized = str(product_ticker or "").strip().upper()
    match = re.fullmatch(r"([0-9A-Z]+)\.([A-Z]{2})", normalized)
    return f"{match.group(1)} {match.group(2)} Equity" if match else normalized


def load_monthly_turnover(*, product_ticker: str, report_date: date) -> dict[str, Any]:
    """Load one Bloomberg monthly turnover aggregate from the DA Report snapshot.

    The upstream row carries both inputs requested by the business formula: ``INTERVAL_SUM`` and
    the trading-day count. The returned average is recomputed with ``Decimal``; the stored DOUBLE
    is retained only as source evidence and checked to six decimal places.
    """
    source = _data_source()
    month_start = report_date.replace(day=1)
    bloomberg_ticker = _bloomberg_equity_ticker(product_ticker)
    with _connect_source(source) as connection:
        actual = _table_columns(connection, "market_monthly_turnovers")
        missing = sorted(MONTHLY_TURNOVER_REQUIRED_COLUMNS - actual)
        if missing:
            raise DaReportProviderError(
                "DA_REPORT_MONTHLY_TURNOVER_NOT_AVAILABLE",
                "The DA-Report snapshot does not contain the Bloomberg monthly-turnover contract.",
                404,
            )
        records = list(connection.execute(text("""
            SELECT id, bloomberg_ticker, calendar_ticker, month_start, period_start, period_end,
                   total_turnover, trading_days, average_daily_turnover, currency, fetched_at
            FROM market_monthly_turnovers
            WHERE UPPER(bloomberg_ticker) = :bloomberg_ticker
              AND month_start = :month_start
            ORDER BY id
        """), {
            "bloomberg_ticker": bloomberg_ticker.upper(),
            "month_start": month_start.isoformat(),
        }).mappings())
    if not records:
        raise DaReportProviderError(
            "DA_REPORT_MONTHLY_TURNOVER_NOT_FOUND",
            f"DA-Report has no completed Bloomberg turnover record for {bloomberg_ticker} in {report_date:%Y-%m}.",
            404,
        )
    if len(records) != 1:
        raise DaReportProviderError(
            "DA_REPORT_MONTHLY_TURNOVER_DUPLICATE",
            f"DA-Report has more than one Bloomberg turnover record for {bloomberg_ticker} in {report_date:%Y-%m}.",
            422,
        )

    record = dict(records[0])
    try:
        total_turnover = Decimal(str(record["total_turnover"]))
        trading_day_count = int(record["trading_days"])
        source_average = Decimal(str(record["average_daily_turnover"]))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise DaReportProviderError(
            "DA_REPORT_MONTHLY_TURNOVER_INVALID",
            "The Bloomberg monthly-turnover row contains a non-numeric formula input.",
            422,
        ) from error
    currency = str(record.get("currency") or "").strip().upper()
    expected_start = month_start.isoformat()
    expected_end = report_date.isoformat()
    period_valid = (
        str(record.get("month_start")) == expected_start
        and str(record.get("period_start")) == expected_start
        and str(record.get("period_end")) == expected_end
    )
    numeric_inputs_valid = (
        total_turnover.is_finite()
        and total_turnover >= 0
        and source_average.is_finite()
        and source_average >= 0
        and trading_day_count > 0
    )
    calculated_average = (
        total_turnover / Decimal(trading_day_count)
        if numeric_inputs_valid else None
    )
    average_matches = (
        calculated_average is not None
        and abs(calculated_average - source_average) <= Decimal("0.000001")
    )
    if (
        not numeric_inputs_valid
        or not re.fullmatch(r"[A-Z]{3}", currency)
        or not period_valid
        or not average_matches
    ):
        raise DaReportProviderError(
            "DA_REPORT_MONTHLY_TURNOVER_INVALID",
            "The Bloomberg monthly-turnover row failed its period, currency or formula checks.",
            422,
        )

    row = {
        "_source_id": int(record["id"]),
        "bloomberg_ticker": str(record["bloomberg_ticker"]),
        "calendar_ticker": str(record["calendar_ticker"]),
        "month_start": expected_start,
        "period_start": expected_start,
        "period_end": expected_end,
        "total_turnover": format(total_turnover, "f"),
        "trading_days": trading_day_count,
        "average_daily_turnover": format(calculated_average, "f"),
        "source_average_daily_turnover": format(source_average, "f"),
        "currency": currency,
        "unit": "unit",
        "source": "Bloomberg",
        "formula": "INTERVAL_SUM(TURNOVER) / trading_days",
        "source_updated_at": str(record["fetched_at"]),
    }
    metadata = _monthly_dataset_metadata(
        source,
        "market_monthly_turnovers",
        [row],
        {"from": expected_start, "to": expected_end},
    )
    metadata["mapping_version"] = "da-report-bloomberg-turnover-v1"
    metadata["lineage"].update({
        "source_field_map": {
            "total_turnover": "total_turnover (Bloomberg INTERVAL_SUM, MARKET_DATA_OVERRIDE=TURNOVER)",
            "trading_days": "trading_days",
            "average_daily_turnover": "total_turnover / trading_days",
            "currency": "currency",
            "unit": "Bloomberg turnover currency amount",
        },
        "product_mapping": {
            "product_ticker": product_ticker,
            "bloomberg_ticker": bloomberg_ticker,
        },
    })
    row.pop("_source_id", None)
    return {
        "fund_turnover_monthly": [row],
        "datasets": {"fund_turnover_monthly": metadata},
        "source_checksum": _source_checksum(source, {"fund_turnover_monthly": metadata}),
    }


def _published_at(value: str | datetime) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _catalog_filter_signature(
    query: str | None,
    source: str | None,
    sentiment: str | None,
    importance: str | None,
    from_date: date | None,
    to_date: date | None,
    company: str | None,
    company_scope: str | None,
) -> str:
    payload = {
        "query": (query or "").strip(),
        "source": source or "",
        "sentiment": sentiment or "",
        "importance": importance or "",
        "from_date": from_date.isoformat() if from_date else "",
        "to_date": to_date.isoformat() if to_date else "",
        "company": company or "",
        "company_scope": company_scope or "",
    }
    encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _encode_catalog_cursor(effective_at: str, external_id: int, sort: str, signature: str) -> str:
    payload = json.dumps({
        "v": 1,
        "effective_at": effective_at,
        "external_id": external_id,
        "sort": sort,
        "signature": signature,
    }, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_catalog_cursor(cursor: str, sort: str, signature: str) -> tuple[str, int]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
        if (
            payload.get("v") != 1
            or payload.get("sort") != sort
            or payload.get("signature") != signature
            or not isinstance(payload.get("effective_at"), str)
            or not isinstance(payload.get("external_id"), int)
        ):
            raise ValueError
        return payload["effective_at"], payload["external_id"]
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeDecodeError, json.JSONDecodeError, binascii.Error) as error:
        raise DaReportProviderError(
            "DA_REPORT_CURSOR_INVALID",
            "The DA-Report company news cursor does not match this query.",
            422,
        ) from error


def _catalog_item(row: Any) -> dict[str, Any]:
    source_name_zh_hans = traditional_to_simplified(row["source_name_zh"]) if row["source_name_zh"] else None
    title_zh_hans = traditional_to_simplified(row["title_zh"]) if row["title_zh"] else None
    summary_zh_hans = traditional_to_simplified(row["summary_zh"]) if row["summary_zh"] else None
    return {
        "provider": "DA_REPORT",
        "external_id": str(row["external_id"]),
        "source_url": str(row["url"]),
        "source_code": row["source_code"],
        "source_name": row["source_name_en"] or row["source_name_zh"] or row["source_code"],
        "source_name_zh": row["source_name_zh"],
        "source_name_zh_hans": source_name_zh_hans,
        "source_name_zh_hans_source": "OPENCC_T2S" if source_name_zh_hans else "MISSING",
        "published_at": _published_at(str(row["effective_at"])),
        "published_at_source": "published_at" if row["published_at"] else "fetched_at",
        "fetched_at": str(row["fetched_at"]),
        "title": row["title_en"] or row["title_zh"] or row["title_raw"] or "",
        "title_en": row["title_en"],
        "title_zh": row["title_zh"],
        "title_zh_hans": title_zh_hans,
        "title_zh_hans_source": "OPENCC_T2S" if title_zh_hans else "MISSING",
        "summary": row["summary_en"] or row["summary_zh"] or row["summary_raw"] or "",
        "summary_en": row["summary_en"],
        "summary_zh": row["summary_zh"],
        "summary_zh_hans": summary_zh_hans,
        "summary_zh_hans_source": "OPENCC_T2S" if summary_zh_hans else "MISSING",
        "category": row["category"],
        "region": row["region"],
        "sentiment": row["sentiment"],
        "importance_score": row["importance_score"],
        "model": row["model"],
    }


def _list_company_news_catalog_sync(
    data_source: _DataSource,
    query: str | None,
    source: str | None,
    sentiment: str | None,
    importance: str | None,
    from_date: date | None,
    to_date: date | None,
    sort: str,
    cursor: str | None,
    limit: int,
    constituents: list[dict[str, Any]],
    company: str | None,
    company_scope: str | None,
) -> dict[str, Any]:
    if sort not in {"newest", "oldest"}:
        raise DaReportProviderError("DA_REPORT_SORT_INVALID", "News sort must be newest or oldest.", 422)
    if not 1 <= limit <= 100:
        raise DaReportProviderError("DA_REPORT_LIMIT_INVALID", "News page size must be between 1 and 100.", 422)
    if from_date and to_date and from_date > to_date:
        raise DaReportProviderError("DA_REPORT_DATE_RANGE_INVALID", "News dates must be ordered.", 422)

    base_from = """
        FROM news_items i
        JOIN news_enrichments e ON e.news_item_id = i.id
        JOIN news_sources s ON s.id = i.source_id
    """
    predicates = [
        "s.report_type = :report_type",
        "e.category = :category",
        "i.url IS NOT NULL",
        "TRIM(i.url) <> ''",
        "COALESCE(i.published_at, i.fetched_at) IS NOT NULL",
    ]
    parameters: dict[str, Any] = {"report_type": "regional", "category": "Corporate"}
    terms = (query or "").strip().split()
    for index, term in enumerate(terms):
        key = f"query_{index}"
        search_text = _joined_text(data_source, ("e.title_en", "e.title_zh", "e.summary_en", "e.summary_zh",
                                                  "i.title_raw", "i.summary_raw", "s.name_en", "s.name_zh"))
        predicates.append(f"LOWER({search_text}) LIKE :{key}")
        parameters[key] = f"%{term.casefold()}%"
    normalized_company = (company or "").strip()
    normalized_company_scope = (company_scope or "").strip().upper()
    if normalized_company_scope not in {"", "CONSTITUENTS"}:
        raise DaReportProviderError(
            "DA_REPORT_COMPANY_SCOPE_INVALID",
            "Company scope must be CONSTITUENTS when supplied.",
            422,
        )
    if normalized_company and normalized_company_scope:
        raise DaReportProviderError(
            "DA_REPORT_COMPANY_FILTER_CONFLICT",
            "Choose either one company or the complete constituent scope, not both.",
            422,
        )
    if normalized_company_scope and not constituents:
        raise DaReportProviderError(
            "DA_REPORT_CONSTITUENTS_UNAVAILABLE",
            "The report-month constituent company list is unavailable.",
            422,
        )
    title_expression = _joined_text(data_source, ("e.title_en", "e.title_zh", "i.title_raw"))
    if normalized_company:
        selected_company = next(
            (
                row for row in constituents
                if str(row.get("security_code") or "").strip() == normalized_company
            ),
            None,
        )
        if selected_company is None:
            raise DaReportProviderError(
                "DA_REPORT_COMPANY_INVALID",
                "The selected company is not part of this report's constituent snapshot.",
                422,
            )
        aliases = _company_aliases(selected_company)
        if aliases:
            company_predicates: list[str] = []
            for index, alias in enumerate(aliases):
                key = f"company_alias_{index}"
                company_predicates.append(_company_predicate(data_source, title_expression, key, alias, parameters))
            predicates.append("(" + " OR ".join(company_predicates) + ")")
        else:
            predicates.append("0 = 1")
    elif normalized_company_scope == "CONSTITUENTS":
        aliases: list[str] = []
        for constituent in constituents:
            for alias in _company_aliases(constituent):
                if alias not in aliases:
                    aliases.append(alias)
        if aliases:
            company_predicates = []
            for index, alias in enumerate(aliases):
                key = f"constituent_alias_{index}"
                company_predicates.append(_company_predicate(data_source, title_expression, key, alias, parameters))
            predicates.append("(" + " OR ".join(company_predicates) + ")")
        else:
            predicates.append("0 = 1")
    if source:
        predicates.append("s.code = :source")
        parameters["source"] = source
    if sentiment:
        predicates.append("LOWER(e.sentiment) = :sentiment")
        parameters["sentiment"] = sentiment.casefold()
    if importance:
        normalized_importance = importance.upper()
        importance_predicates = {
            "HIGH": "e.importance_score >= 70",
            "MEDIUM": "e.importance_score >= 40 AND e.importance_score < 70",
            "LOW": "e.importance_score < 40",
        }
        if normalized_importance not in importance_predicates:
            raise DaReportProviderError("DA_REPORT_IMPORTANCE_INVALID", "News importance is invalid.", 422)
        predicates.append(importance_predicates[normalized_importance])
    if from_date:
        predicates.append("COALESCE(i.published_at, i.fetched_at) >= :from_date")
        parameters["from_date"] = from_date.isoformat()
    if to_date:
        predicates.append("COALESCE(i.published_at, i.fetched_at) < :to_date_exclusive")
        parameters["to_date_exclusive"] = (to_date + timedelta(days=1)).isoformat()

    where_sql = " WHERE " + " AND ".join(f"({predicate})" for predicate in predicates)
    signature = _catalog_filter_signature(
        query,
        source,
        sentiment,
        importance,
        from_date,
        to_date,
        normalized_company,
        normalized_company_scope,
    )
    page_predicates = list(predicates)
    if cursor:
        cursor_at, cursor_id = _decode_catalog_cursor(cursor, sort, signature)
        comparison = "<" if sort == "newest" else ">"
        page_predicates.append(
            f"(COALESCE(i.published_at, i.fetched_at) {comparison} :cursor_at OR "
            f"(COALESCE(i.published_at, i.fetched_at) = :cursor_at AND i.id {comparison} :cursor_id))"
        )
        parameters.update({"cursor_at": cursor_at, "cursor_id": cursor_id})
    page_where_sql = " WHERE " + " AND ".join(f"({predicate})" for predicate in page_predicates)
    direction = "DESC" if sort == "newest" else "ASC"
    catalog_query = text("""
        SELECT
            i.id AS external_id,
            i.url,
            i.title_raw,
            i.summary_raw,
            i.published_at,
            i.fetched_at,
            s.code AS source_code,
            s.name_en AS source_name_en,
            s.name_zh AS source_name_zh,
            e.title_en,
            e.title_zh,
            e.summary_en,
            e.summary_zh,
            e.category,
            e.region,
            e.sentiment,
            e.importance_score,
            e.model,
            COALESCE(i.published_at, i.fetched_at) AS effective_at
    """ + base_from + page_where_sql + f"""
        ORDER BY effective_at {direction}, i.id {direction}
        LIMIT :limit
    """)
    try:
        with _connect_source(data_source) as connection:
            _validate_schema(connection)
            rows = list(connection.execute(catalog_query, {**parameters, "limit": limit + 1}).mappings())
            total = int(connection.execute(
                text("SELECT COUNT(*) " + base_from + where_sql),
                parameters,
            ).scalar_one())
            facet_where = """
                WHERE s.report_type = 'regional'
                  AND e.category = 'Corporate'
                  AND i.url IS NOT NULL
                  AND TRIM(i.url) <> ''
                  AND COALESCE(i.published_at, i.fetched_at) IS NOT NULL
            """
            sentiments = {
                str(row["value"]): int(row["count"])
                for row in connection.execute(text(
                    "SELECT e.sentiment AS value, COUNT(*) AS count " + base_from + facet_where +
                    "GROUP BY e.sentiment ORDER BY count DESC"
                )).mappings()
                if row["value"] is not None
            }
            sources = [{
                "value": str(row["value"]),
                "label": row["label"] or row["label_zh"] or row["value"],
                "label_zh": row["label_zh"],
                "label_zh_hans": traditional_to_simplified(row["label_zh"]) if row["label_zh"] else None,
                "count": int(row["count"]),
            } for row in connection.execute(text(
                "SELECT s.code AS value, s.name_en AS label, s.name_zh AS label_zh, COUNT(*) AS count "
                + base_from + facet_where +
                "GROUP BY s.code, s.name_en, s.name_zh ORDER BY count DESC, s.code ASC"
            )).mappings()]
            importance_counts = {
                str(row["value"]): int(row["count"])
                for row in connection.execute(text(
                    "SELECT CASE WHEN e.importance_score >= 70 THEN 'HIGH' "
                    "WHEN e.importance_score < 40 THEN 'LOW' ELSE 'MEDIUM' END AS value, "
                    "COUNT(*) AS count " + base_from + facet_where +
                    "GROUP BY value ORDER BY count DESC"
                )).mappings()
            }
            date_bounds = connection.execute(text(
                "SELECT MIN(SUBSTR(COALESCE(i.published_at, i.fetched_at), 1, 10)) AS date_min, "
                "MAX(SUBSTR(COALESCE(i.published_at, i.fetched_at), 1, 10)) AS date_max "
                + base_from + facet_where
            )).mappings().one()
    except DaReportProviderError:
        raise
    except (SQLAlchemyError, OSError, ValueError) as error:
        raise DaReportProviderError(
            "DA_REPORT_UNAVAILABLE",
            "The DA-Report company news catalog could not be queried.",
            503,
            retryable=True,
        ) from error

    page_rows = rows[:limit]
    items = [_catalog_item(row) for row in page_rows]
    next_cursor = None
    if len(rows) > limit and page_rows:
        last = page_rows[-1]
        next_cursor = _encode_catalog_cursor(
            str(last["effective_at"]),
            int(last["external_id"]),
            sort,
            signature,
        )
    return {
        "items": items,
        "total": total,
        "has_more": len(rows) > limit,
        "next_cursor": next_cursor,
        "facets": {
            "companies": _company_facets(constituents),
            "sources": sources,
            "sentiments": sentiments,
            "importance": importance_counts,
            "date_min": date_bounds["date_min"],
            "date_max": date_bounds["date_max"],
        },
    }


def _list_configured_catalog_sync(*args):
    return _list_company_news_catalog_sync(_data_source(), *args)


async def list_company_news_catalog(
    query: str | None = None,
    source: str | None = None,
    sentiment: str | None = None,
    importance: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    sort: Literal["newest", "oldest"] = "newest",
    cursor: str | None = None,
    limit: int = 50,
    constituents: list[dict[str, Any]] | None = None,
    company: str | None = None,
    company_scope: Literal["CONSTITUENTS"] | None = None,
) -> dict[str, Any]:
    return await asyncio.to_thread(
        _list_configured_catalog_sync,
        query,
        source,
        sentiment,
        importance,
        from_date,
        to_date,
        sort,
        cursor,
        limit,
        constituents or [],
        company,
        company_scope,
    )


def _get_company_news_catalog_item_sync(source: _DataSource, external_id: str) -> dict[str, Any]:
    try:
        item_id = int(external_id)
    except (TypeError, ValueError) as error:
        raise DaReportProviderError(
            "DA_REPORT_NEWS_NOT_FOUND",
            "The selected DA-Report company news item does not exist.",
            422,
        ) from error
    query = text("""
        SELECT
            i.id AS external_id,
            i.url,
            i.title_raw,
            i.summary_raw,
            i.published_at,
            i.fetched_at,
            s.code AS source_code,
            s.name_en AS source_name_en,
            s.name_zh AS source_name_zh,
            e.title_en,
            e.title_zh,
            e.summary_en,
            e.summary_zh,
            e.category,
            e.region,
            e.sentiment,
            e.importance_score,
            e.model,
            COALESCE(i.published_at, i.fetched_at) AS effective_at
        FROM news_items i
        JOIN news_enrichments e ON e.news_item_id = i.id
        JOIN news_sources s ON s.id = i.source_id
        WHERE i.id = :external_id
          AND s.report_type = 'regional'
          AND e.category = 'Corporate'
          AND i.url IS NOT NULL
          AND TRIM(i.url) <> ''
          AND COALESCE(i.published_at, i.fetched_at) IS NOT NULL
    """)
    try:
        with _connect_source(source) as connection:
            _validate_schema(connection)
            row = connection.execute(query, {"external_id": item_id}).mappings().one_or_none()
    except DaReportProviderError:
        raise
    except (SQLAlchemyError, OSError, ValueError) as error:
        raise DaReportProviderError(
            "DA_REPORT_UNAVAILABLE",
            "The DA-Report company news catalog could not be queried.",
            503,
            retryable=True,
        ) from error
    if row is None:
        raise DaReportProviderError(
            "DA_REPORT_NEWS_NOT_FOUND",
            "The selected DA-Report company news item does not exist.",
            422,
        )
    return _catalog_item(row)


async def get_company_news_catalog_item(external_id: str) -> dict[str, Any]:
    return await asyncio.to_thread(
        lambda: _get_company_news_catalog_item_sync(_data_source(), external_id),
    )


def _fetch_sync(
    source: _DataSource,
    constituents: list[dict[str, Any]],
    from_date: date,
    to_date: date,
    page: int,
    limit: int,
) -> list[dict[str, Any]]:
    aliases = _constituent_aliases(constituents)
    if not aliases:
        return []
    query = text("""
        SELECT
            i.id AS external_id,
            i.url,
            i.title_raw,
            i.summary_raw,
            i.published_at,
            i.fetched_at,
            s.code AS source_code,
            s.name_en AS source_name_en,
            s.name_zh AS source_name_zh,
            e.title_en,
            e.title_zh,
            e.summary_en,
            e.summary_zh,
            e.region,
            e.sentiment,
            e.importance_score,
            e.model
        FROM news_items i
        JOIN news_enrichments e ON e.news_item_id = i.id
        JOIN news_sources s ON s.id = i.source_id
        WHERE s.report_type = :report_type
          AND e.category = :category
          AND i.published_at >= :from_timestamp
          AND i.published_at < :to_timestamp
          AND i.url IS NOT NULL
          AND TRIM(i.url) <> ''
        ORDER BY e.importance_score DESC, i.published_at DESC, i.id DESC
    """)
    try:
        with _connect_source(source) as connection:
            _validate_schema(connection)
            rows = connection.execute(query, {
                "report_type": "regional",
                "category": "Corporate",
                "from_timestamp": from_date.isoformat(),
                "to_timestamp": (to_date + timedelta(days=1)).isoformat(),
            }).mappings()
            candidates: list[dict[str, Any]] = []
            seen_urls: set[str] = set()
            for row in rows:
                match = _match_title(row["title_en"], row["title_zh"], aliases)
                source_url = str(row["url"]).strip()
                if match is None or source_url in seen_urls:
                    continue
                matched_alias, security_code, ticker = match
                seen_urls.add(source_url)
                candidates.append({
                    "source_name": row["source_name_en"] or row["source_name_zh"] or row["source_code"],
                    "source_url": source_url,
                    "published_at": _published_at(str(row["published_at"])),
                    "title": row["title_en"] or row["title_zh"] or row["title_raw"],
                    "summary": row["summary_en"] or row["summary_zh"] or row["summary_raw"] or "",
                    "ticker": ticker,
                    "metadata_json": {
                        "provider": "DA_REPORT",
                        "scope": "CONSTITUENTS",
                        "site": urlparse(source_url).hostname,
                        "external_id": str(row["external_id"]),
                        "source_name_en": row["source_name_en"],
                        "source_name_zh": row["source_name_zh"],
                        "title_en": row["title_en"],
                        "title_zh": row["title_zh"],
                        "summary_en": row["summary_en"],
                        "summary_zh": row["summary_zh"],
                        "source_code": row["source_code"],
                        "fetched_at": str(row["fetched_at"]),
                        "region": row["region"],
                        "sentiment": row["sentiment"],
                        "importance_score": row["importance_score"],
                        "model": row["model"],
                        "matched_security_code": security_code,
                        "matched_alias": matched_alias,
                        "match_method": "TITLE_ALIAS_EXACT",
                    },
                })
    except DaReportProviderError:
        raise
    except (SQLAlchemyError, OSError, ValueError) as error:
        raise DaReportProviderError(
            "DA_REPORT_UNAVAILABLE",
            "The DA-Report news snapshot could not be queried.",
            503,
            retryable=True,
        ) from error
    start = page * limit
    return candidates[start:start + limit]


def _fetch_configured_sync(
    constituents: list[dict[str, Any]],
    from_date: date,
    to_date: date,
    page: int,
    limit: int,
) -> list[dict[str, Any]]:
    return _fetch_sync(_data_source(), constituents, from_date, to_date, page, limit)


async def fetch_news(
    scope: Literal["CONSTITUENTS", "GENERAL"],
    symbols: list[str],
    from_date: date,
    to_date: date,
    page: int,
    limit: int,
    client=None,
    constituents: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    del symbols, client
    if scope != "CONSTITUENTS":
        raise DaReportProviderError(
            "DA_REPORT_SCOPE_UNSUPPORTED",
            "DA-Report candidates require the current report constituent snapshot.",
            422,
        )
    if not constituents:
        raise DaReportProviderError(
            "DA_REPORT_CONSTITUENTS_REQUIRED",
            "DA-Report candidates require the current report constituent snapshot.",
            422,
        )
    return await asyncio.to_thread(
        _fetch_configured_sync,
        constituents,
        from_date,
        to_date,
        page,
        limit,
    )
