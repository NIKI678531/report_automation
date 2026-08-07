from __future__ import annotations

import hashlib
from datetime import date, datetime, timezone
from typing import Any, Literal
from urllib.parse import urlparse

import httpx

from app.core.config import settings
from app.integrations.news import NewsProviderError


class FmpProviderError(NewsProviderError):
    """Kept as its own name so existing callers and tests still catch what they expect."""


def _provider_url(path: str) -> str:
    parsed = urlparse(settings.fmp_base_url)
    if parsed.scheme != "https" or (parsed.hostname or "").lower() not in settings.fmp_allowed_hosts:
        raise FmpProviderError("FMP_HOST_NOT_ALLOWED", "FMP base URL is not an approved HTTPS host.", 503)
    return f"{settings.fmp_base_url.rstrip('/')}/{path.lstrip('/')}"


def _published_at(value: Any) -> datetime:
    text = str(value or "").strip()
    for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            parsed = datetime.strptime(text, pattern)
            return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
        except ValueError:
            continue
    raise FmpProviderError("FMP_RESPONSE_INVALID", "FMP returned an invalid publication timestamp.", 502)


def normalize_news_item(item: dict[str, Any], scope: str) -> dict[str, Any]:
    source_url = str(item.get("url") or "").strip()
    parsed_url = urlparse(source_url)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
        raise FmpProviderError("FMP_RESPONSE_INVALID", "FMP returned an invalid article URL.", 502)
    title = str(item.get("title") or "").strip()
    if not title:
        raise FmpProviderError("FMP_RESPONSE_INVALID", "FMP returned an article without a title.", 502)
    published_at = _published_at(item.get("publishedDate"))
    symbol = str(item.get("symbol") or "").strip().upper() or None
    publisher = str(item.get("publisher") or item.get("site") or "FMP").strip()
    dedupe_material = f"{symbol or ''}|{published_at.isoformat()}|{title}|{source_url}"
    return {
        "source_name": publisher,
        "source_url": source_url,
        "published_at": published_at,
        "title": title,
        "summary": str(item.get("text") or "").strip(),
        "ticker": symbol,
        "metadata_json": {
            "provider": "FMP", "scope": scope, "site": item.get("site"), "image_url": item.get("image"),
            "dedupe_hash": hashlib.sha256(dedupe_material.encode("utf-8")).hexdigest(), "fetched_at": datetime.now(timezone.utc).isoformat(),
        },
    }


async def fetch_news(
    scope: Literal["CONSTITUENTS", "GENERAL"],
    symbols: list[str],
    from_date: date,
    to_date: date,
    page: int,
    limit: int,
    client: httpx.AsyncClient | None = None,
) -> list[dict[str, Any]]:
    if not settings.fmp_api_key:
        raise FmpProviderError("FMP_NOT_CONFIGURED", "FMP news is not configured for this environment.", 503)
    path = "news/stock" if scope == "CONSTITUENTS" else "news/general-latest"
    params: dict[str, Any] = {"from": from_date.isoformat(), "to": to_date.isoformat(), "page": page, "limit": min(limit, settings.fmp_max_results, 250)}
    if scope == "CONSTITUENTS":
        params["symbols"] = ",".join(symbols)
    request_client = client or httpx.AsyncClient(timeout=settings.fmp_timeout_seconds)
    try:
        response = await request_client.get(_provider_url(path), params=params, headers={"apikey": settings.fmp_api_key, "Accept": "application/json"})
    except httpx.TimeoutException as error:
        raise FmpProviderError("FMP_TIMEOUT", "FMP news request timed out.", 504, True) from error
    except httpx.RequestError as error:
        raise FmpProviderError("FMP_UNAVAILABLE", "FMP news request failed.", 502, True) from error
    finally:
        if client is None:
            await request_client.aclose()
    if response.status_code in {401, 403}:
        raise FmpProviderError("FMP_AUTH_FAILED", "FMP rejected the configured credentials.", 502)
    if response.status_code == 429:
        raise FmpProviderError("FMP_RATE_LIMITED", "FMP rate limit was reached.", 503, True)
    if response.status_code >= 500:
        raise FmpProviderError("FMP_UNAVAILABLE", "FMP news service is unavailable.", 502, True)
    if response.status_code >= 400:
        raise FmpProviderError("FMP_REQUEST_REJECTED", "FMP rejected the news request.", 502)
    try:
        payload = response.json()
    except ValueError as error:
        raise FmpProviderError("FMP_RESPONSE_INVALID", "FMP returned invalid JSON.", 502) from error
    if not isinstance(payload, list):
        raise FmpProviderError("FMP_RESPONSE_INVALID", "FMP returned an unexpected response shape.", 502)
    normalized = []
    seen: set[str] = set()
    for item in payload:
        candidate = normalize_news_item(item, scope)
        # news/general-latest ignores from/to and always returns the newest page, so the window is
        # enforced here to keep both scopes honest about the range the user asked for.
        published_date = candidate["published_at"].date()
        if published_date < from_date or published_date > to_date:
            continue
        dedupe_hash = candidate["metadata_json"]["dedupe_hash"]
        if dedupe_hash not in seen:
            seen.add(dedupe_hash)
            normalized.append(candidate)
    return normalized