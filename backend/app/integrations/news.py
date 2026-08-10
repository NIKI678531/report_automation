"""Provider-neutral news fetching.

The report route used to import ``app.integrations.fmp`` directly, so FMP was the only source a report
could ever draw from and its error class was the only failure the route knew how to render. Providers
now register a spec here and the caller selects one by key; every adapter raises ``NewsProviderError``
and returns the same normalized candidate shape, so nothing downstream knows which vendor answered.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from importlib import import_module
from typing import Any, Literal

import httpx

from app.core.config import settings


class NewsProviderError(Exception):
    """A provider failure the caller must surface verbatim — never with the URL or the credential in it."""

    def __init__(self, code: str, message: str, http_status: int, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.retryable = retryable


@dataclass(frozen=True)
class NewsProviderSpec:
    key: str
    title: str
    description: str
    #: Imported lazily, so a provider nobody selected never loads and never reads its secret.
    module: str
    secret_setting: str | None
    auth_style: Literal["HEADER", "QUERY", "NONE"]
    needs_constituent_context: bool = False


REGISTRY: dict[str, NewsProviderSpec] = {
    "FMP": NewsProviderSpec(
        key="FMP",
        title="Financial Modeling Prep",
        description="Stock and general market news, filtered by ticker and date window.",
        module="app.integrations.fmp",
        secret_setting="fmp_api_key",
        auth_style="HEADER",
    ),
    "MARKETAUX": NewsProviderSpec(
        key="MARKETAUX",
        title="Marketaux",
        description="Global equity news with per-article entity tagging, including Hong Kong listings.",
        module="app.integrations.marketaux",
        secret_setting="marketaux_api_key",
        # Marketaux has no header auth: `api_token` is a query parameter or nothing. See
        # docs/fmp-news-and-data-imports.md for the deviation and how the key is kept out of logs.
        auth_style="QUERY",
    ),
    "DA_REPORT": NewsProviderSpec(
        key="DA_REPORT",
        title="DA-Report",
        description="Approved regional company news matched strictly to the active constituent snapshot.",
        module="app.integrations.da_report",
        secret_setting=None,
        auth_style="NONE",
        needs_constituent_context=True,
    ),
}

DEFAULT_PROVIDER = "FMP"


def get_spec(key: str | None) -> NewsProviderSpec:
    spec = REGISTRY.get((key or settings.news_provider or DEFAULT_PROVIDER).upper())
    if spec is None:
        raise NewsProviderError(
            "NEWS_PROVIDER_UNKNOWN",
            f"'{key}' is not a configured news provider.",
            422,
        )
    return spec


def is_configured(spec: NewsProviderSpec) -> bool:
    if spec.secret_setting:
        return bool(getattr(settings, spec.secret_setting, None))
    adapter = import_module(spec.module)
    checker = getattr(adapter, "is_configured", None)
    return bool(checker and checker())


def list_providers() -> list[dict[str, Any]]:
    """Which providers exist and which of them actually hold a credential in this environment.

    Only the boolean is exposed. The credential itself never leaves the process.
    """
    return [
        {
            "key": spec.key,
            "title": spec.title,
            "description": spec.description,
            "configured": is_configured(spec),
            "default": spec.key == (settings.news_provider or DEFAULT_PROVIDER).upper(),
        }
        for spec in REGISTRY.values()
    ]


async def fetch_news(
    provider: str | None,
    scope: Literal["CONSTITUENTS", "GENERAL"],
    symbols: list[str],
    from_date: date,
    to_date: date,
    page: int,
    limit: int,
    client: httpx.AsyncClient | None = None,
    constituents: list[dict[str, Any]] | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    """Dispatch to the selected adapter and return ``(provider_key, candidates)``."""
    spec = get_spec(provider)
    adapter = import_module(spec.module)
    # `client` stays out of the call unless a caller supplied one, so adapters (and the test doubles
    # that stand in for them) keep the six-argument signature they already have.
    if spec.needs_constituent_context:
        candidates = await adapter.fetch_news(
            scope,
            symbols,
            from_date,
            to_date,
            page,
            limit,
            constituents=constituents,
        )
    elif client is None:
        candidates = await adapter.fetch_news(scope, symbols, from_date, to_date, page, limit)
    else:
        candidates = await adapter.fetch_news(scope, symbols, from_date, to_date, page, limit, client)
    return spec.key, candidates
