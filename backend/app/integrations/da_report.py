from __future__ import annotations

import asyncio
import hashlib
import os
import re
import threading
import unicodedata
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

import httpx
from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings
from app.integrations.news import NewsProviderError


REQUIRED_COLUMNS = {
    "news_sources": {"id", "name_en", "name_zh", "report_type"},
    "news_items": {
        "id", "source_id", "url", "title_raw", "summary_raw", "published_at", "fetched_at",
    },
    "news_enrichments": {
        "news_item_id", "title_en", "title_zh", "summary_en", "summary_zh", "category",
        "region", "sentiment", "importance_score", "model",
    },
}
_NON_WORD = re.compile(r"[^0-9A-Za-z\u3400-\u9fff]+")
_LATIN_BOUNDARY = r"0-9A-Z"
_LISTING_SUFFIXES = {"S", "SW", "W"}
_MATERIALIZE_LOCK = threading.Lock()


class DaReportProviderError(NewsProviderError):
    pass


def is_configured() -> bool:
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
        dbapi_connection.execute("PRAGMA query_only=ON")

    return engine


def _validate_schema(connection) -> None:
    for table_name, required in REQUIRED_COLUMNS.items():
        rows = connection.execute(text(f"PRAGMA table_info({table_name})")).mappings()
        actual = {str(row["name"]) for row in rows}
        missing = sorted(required - actual)
        if missing:
            raise DaReportProviderError(
                "DA_REPORT_SCHEMA_MISMATCH",
                f"The DA-Report snapshot is missing required fields in {table_name}: {', '.join(missing)}.",
                503,
            )


def _published_at(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _fetch_sync(
    path: Path,
    constituents: list[dict[str, Any]],
    from_date: date,
    to_date: date,
    page: int,
    limit: int,
) -> list[dict[str, Any]]:
    _verify_file(path)
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
        with _engine(str(path.resolve())).connect() as connection:
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
                        "source_code": row["source_code"],
                        "fetched_at": row["fetched_at"],
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
    return _fetch_sync(_materialize_snapshot(), constituents, from_date, to_date, page, limit)


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