"""Marketaux news adapter.

Marketaux tags every article with the entities it mentions, so one article can carry several symbols.
FMP returns one row per symbol; here the article is emitted once and bound to the requested symbol it
matches, with the full matched set kept in metadata for traceability.

**Credential handling deviates from the FMP rule and the deviation is deliberate.** Marketaux accepts
`api_token` as a query parameter only — it has no header auth — so the key necessarily appears in the
outbound URL. Nothing in this module ever puts a URL into an exception message, a log record, an audit
entry or a normalized candidate, which is where the rule in docs/fmp-news-and-data-imports.md actually
bites. `_redact` is the backstop for anything that slips through.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime, timezone
from typing import Any, Literal
from urllib.parse import urlparse

import httpx

from app.core.config import settings
from app.integrations.news import NewsProviderError

#: Marketaux caps a single page at 100 articles regardless of plan.
MAX_PAGE_SIZE = 100


class MarketauxProviderError(NewsProviderError):
    pass


def _redact(text: str) -> str:
    """Last line of defence: never let a configured token reach a message we are about to surface."""
    key = settings.marketaux_api_key
    return text.replace(key, "***") if key else text


def _error_detail(response: httpx.Response) -> str:
    """Marketaux explains rejections in the body; without it the user only sees 'rejected'.

    The body can echo the request parameters back, and `api_token` is one of them, so it is redacted
    before it becomes part of a message that reaches the API response.
    """
    try:
        payload = response.json()
    except ValueError:
        return ""
    error = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(error, dict):
        return ""
    detail = " ".join(str(error.get(field, "")).strip() for field in ("code", "message")).strip()
    return _redact(detail)


def _provider_url(path: str) -> str:
    parsed = urlparse(settings.marketaux_base_url)
    if parsed.scheme != "https" or (parsed.hostname or "").lower() not in settings.marketaux_allowed_hosts:
        raise MarketauxProviderError("MARKETAUX_HOST_NOT_ALLOWED", "Marketaux base URL is not an approved HTTPS host.", 503)
    return f"{settings.marketaux_base_url.rstrip('/')}/{path.lstrip('/')}"


def _published_at(value: Any) -> datetime:
    text = str(value or "").strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
        except ValueError as error:
            raise MarketauxProviderError("MARKETAUX_RESPONSE_INVALID", "Marketaux returned an invalid publication timestamp.", 502) from error
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _matched_symbols(item: dict[str, Any], requested: set[str]) -> list[str]:
    entities = item.get("entities")
    symbols = []
    for entity in entities if isinstance(entities, list) else []:
        symbol = str((entity or {}).get("symbol") or "").strip().upper()
        if symbol and symbol not in symbols:
            symbols.append(symbol)
    # When the caller asked for specific holdings, the requested ones lead: an article about Tencent
    # that also mentions an unrelated US name must still bind to the constituent that was asked for.
    preferred = [symbol for symbol in symbols if symbol in requested]
    return preferred or symbols


def normalize_news_item(item: dict[str, Any], scope: str, requested: set[str] | None = None) -> dict[str, Any]:
    source_url = str(item.get("url") or "").strip()
    parsed_url = urlparse(source_url)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
        raise MarketauxProviderError("MARKETAUX_RESPONSE_INVALID", "Marketaux returned an invalid article URL.", 502)
    title = str(item.get("title") or "").strip()
    if not title:
        raise MarketauxProviderError("MARKETAUX_RESPONSE_INVALID", "Marketaux returned an article without a title.", 502)
    published_at = _published_at(item.get("published_at"))
    matched = _matched_symbols(item, requested or set())
    symbol = matched[0] if matched else None
    site = str(item.get("source") or "").strip() or (parsed_url.hostname or "")
    # `snippet` is the keyword-centred extract; `description` is the article standfirst. Prefer the
    # standfirst, because the snippet is cut mid-sentence around the search term.
    summary = str(item.get("description") or item.get("snippet") or "").strip()
    dedupe_material = f"{symbol or ''}|{published_at.isoformat()}|{title}|{source_url}"
    return {
        "source_name": site or "Marketaux",
        "source_url": source_url,
        "published_at": published_at,
        "title": title,
        "summary": summary,
        "ticker": symbol,
        "metadata_json": {
            "provider": "MARKETAUX", "scope": scope, "site": site, "image_url": item.get("image_url") or None,
            "matched_symbols": matched, "language": item.get("language"), "external_id": item.get("uuid"),
            "dedupe_hash": hashlib.sha256(dedupe_material.encode("utf-8")).hexdigest(),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
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
    if not settings.marketaux_api_key:
        raise MarketauxProviderError("MARKETAUX_NOT_CONFIGURED", "Marketaux news is not configured for this environment.", 503)
    params: dict[str, Any] = {
        "api_token": settings.marketaux_api_key,
        # The window is inclusive of both endpoints, which means the whole of `to_date`.
        "published_after": f"{from_date.isoformat()}T00:00:00",
        "published_before": f"{to_date.isoformat()}T23:59:59",
        # Marketaux pages are 1-based; the shared interface is 0-based like FMP's.
        "page": page + 1,
        "limit": min(limit, settings.marketaux_max_results, MAX_PAGE_SIZE),
        "language": settings.marketaux_language,
    }
    if scope == "CONSTITUENTS":
        params["symbols"] = ",".join(symbols)
        # Without this, an article merely *mentioning* a holding in a market round-up ranks equally
        # with one actually about it, and the constituent feed fills with index commentary.
        params["must_have_entities"] = "true"
    request_client = client or httpx.AsyncClient(timeout=settings.marketaux_timeout_seconds)
    try:
        response = await request_client.get(_provider_url("news/all"), params=params, headers={"Accept": "application/json"})
    except httpx.TimeoutException as error:
        # `from None`: the chained httpx error carries `.request.url`, and that URL contains the
        # api_token. Dropping the cause keeps it out of every traceback and log downstream.
        raise MarketauxProviderError("MARKETAUX_TIMEOUT", "Marketaux news request timed out.", 504, True) from None
    except httpx.RequestError:
        raise MarketauxProviderError("MARKETAUX_UNAVAILABLE", "Marketaux news request failed.", 502, True) from None
    finally:
        if client is None:
            await request_client.aclose()
    if response.status_code in {401, 403}:
        raise MarketauxProviderError("MARKETAUX_AUTH_FAILED", "Marketaux rejected the configured credentials.", 502)
    if response.status_code == 402:
        raise MarketauxProviderError("MARKETAUX_QUOTA_EXCEEDED", "The Marketaux plan quota is exhausted.", 503)
    if response.status_code == 429:
        raise MarketauxProviderError("MARKETAUX_RATE_LIMITED", "Marketaux rate limit was reached.", 503, True)
    if response.status_code >= 500:
        raise MarketauxProviderError("MARKETAUX_UNAVAILABLE", "Marketaux news service is unavailable.", 502, True)
    if response.status_code >= 400:
        detail = _error_detail(response)
        raise MarketauxProviderError("MARKETAUX_REQUEST_REJECTED", f"Marketaux rejected the news request. {detail}".strip(), 502)
    try:
        payload = response.json()
    except ValueError as error:
        raise MarketauxProviderError("MARKETAUX_RESPONSE_INVALID", "Marketaux returned invalid JSON.", 502) from error
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise MarketauxProviderError("MARKETAUX_RESPONSE_INVALID", "Marketaux returned an unexpected response shape.", 502)
    requested = {symbol.strip().upper() for symbol in symbols if symbol.strip()}
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in payload["data"]:
        candidate = normalize_news_item(item, scope, requested)
        # The API filters server-side, but the window is the caller's contract, so it is re-checked
        # here for the same reason the FMP adapter does it: a provider that ignores it must not widen it.
        published_date = candidate["published_at"].date()
        if published_date < from_date or published_date > to_date:
            continue
        dedupe_hash = candidate["metadata_json"]["dedupe_hash"]
        if dedupe_hash not in seen:
            seen.add(dedupe_hash)
            normalized.append(candidate)
    return normalized
