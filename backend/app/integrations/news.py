"""Provider-neutral news fetching.

Providers register a spec here and the caller selects one by key; every adapter raises
``NewsProviderError`` and returns the same normalized candidate shape, so nothing downstream knows
which source answered. ``DA_REPORT`` is the only supported provider and reads the configured
read-only MySQL or SQLite source.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from importlib import import_module
from typing import Any, Literal

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
    #: Imported lazily to avoid a cycle with the adapter's shared error type.
    module: str


REGISTRY: dict[str, NewsProviderSpec] = {
    "DA_REPORT": NewsProviderSpec(
        key="DA_REPORT",
        title="DA-Report",
        description="Approved regional company news matched strictly to the active constituent snapshot.",
        module="app.integrations.da_report",
    ),
}

DEFAULT_PROVIDER = "DA_REPORT"


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
    adapter = import_module(spec.module)
    checker = getattr(adapter, "is_configured", None)
    return bool(checker and checker())


def list_providers() -> list[dict[str, Any]]:
    """Which providers exist and have a data source configured in this environment.

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
    constituents: list[dict[str, Any]] | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    """Dispatch to the selected adapter and return ``(provider_key, candidates)``."""
    spec = get_spec(provider)
    adapter = import_module(spec.module)
    candidates = await adapter.fetch_news(
        scope,
        symbols,
        from_date,
        to_date,
        page,
        limit,
        constituents=constituents,
    )
    return spec.key, candidates
