"""Editorial heading overrides shared by the editor and all report renderers."""

import re
import unicodedata
from datetime import date
from typing import Any

from .localization import localized_portfolio_label, month_name, term
from .metrics.final_analytics import PORTFOLIO_METRIC_ORDER, normalize_portfolio_rows


TITLE_TERMS = (
    "historical_performance", "company_news", "constituent_performance",
    "top10", "sector_breakdown", "performers", "top_performers", "bottom_performers", "portfolio_analysis",
)
TITLE_KEYS = frozenset((*TITLE_TERMS, *(f"portfolio.{code}" for code in PORTFOLIO_METRIC_ORDER)))


def _normalized_bound_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split())


def _amount_qualifier(label: str) -> str:
    normalized = _normalized_bound_text(label)
    start = normalized.rfind("(")
    end = normalized.find(")", start + 1)
    if start >= 0 and end > start:
        return normalized[start + 1:end]
    return ""


def _contains_bound_text(title: str, token: str) -> bool:
    normalized_title = _normalized_bound_text(title)
    normalized_token = _normalized_bound_text(token)
    prefix = r"(?<![0-9A-Za-z])" if normalized_token[:1].isascii() and normalized_token[:1].isalnum() else ""
    suffix = r"(?![0-9A-Za-z])" if normalized_token[-1:].isascii() and normalized_token[-1:].isalnum() else ""
    return re.search(f"{prefix}{re.escape(normalized_token)}{suffix}", normalized_title) is not None


def report_title_required_tokens(content: dict[str, Any]) -> dict[str, tuple[str, ...]]:
    """Return immutable data bindings that an editorial title must retain."""

    language = str(content.get("language_mode") or "EN")
    terminology_value = content.get("terminology_overrides")
    terminology = terminology_value if isinstance(terminology_value, dict) else {}
    product = str(content.get("product_ticker") or "").strip()
    benchmark = str(
        terminology.get("benchmark_name") or content.get("benchmark_name") or ""
    ).strip()
    try:
        month = month_name(date.fromisoformat(str(content.get("report_date"))), language)
    except (TypeError, ValueError):
        month = str(content.get("month_name") or "").strip()

    required: dict[str, tuple[str, ...]] = {
        "historical_performance": tuple(value for value in (product, benchmark) if value),
        "constituent_performance": (product,) if product else (),
        "top10": (product,) if product else (),
        "sector_breakdown": (product,) if product else (),
        "performers": (month,) if month else (),
        "top_performers": (month,) if month else (),
        "bottom_performers": (month,) if month else (),
        "portfolio_analysis": (product,) if product else (),
    }
    sections_value = content.get("sections")
    sections = sections_value if isinstance(sections_value, dict) else {}
    analytics_value = sections.get("analytics")
    analytics = analytics_value if isinstance(analytics_value, dict) else {}
    portfolio = analytics.get("portfolio")
    for row in normalize_portfolio_rows(portfolio):
        code = str(row["metric_code"])
        if code not in {"AUM", "AVERAGE_DAILY_TURNOVER"}:
            continue
        label = localized_portfolio_label(code, row["label"], language)
        qualifier = _amount_qualifier(label)
        required[f"portfolio.{code}"] = (qualifier,) if qualifier else ()
    return required


def missing_report_title_tokens(content: dict[str, Any], key: str, title: str) -> tuple[str, ...]:
    return tuple(
        token
        for token in report_title_required_tokens(content).get(key, ())
        if not _contains_bound_text(title, token)
    )


def report_title_defaults(
    content: dict[str, Any],
    *,
    product_code: str,
    benchmark_name: str,
    report_date: date,
    language_mode: str,
) -> dict[str, str]:
    language = str(content.get("language_mode") or language_mode)
    terminology = content.get("terminology_overrides") or {}
    values = {
        "product": content.get("product_ticker") or f"{product_code}.HK",
        "benchmark": terminology.get("benchmark_name") or content.get("benchmark_name") or benchmark_name,
        "month": month_name(report_date, language),
    }
    titles = {key: term(key, language, **values) for key in TITLE_TERMS}
    portfolio = content.get("sections", {}).get("analytics", {}).get("portfolio")
    for row in normalize_portfolio_rows(portfolio):
        titles[f"portfolio.{row['metric_code']}"] = localized_portfolio_label(
            row["metric_code"], row["label"], language,
        )
    return titles


def resolve_report_titles(content: dict[str, Any], defaults: dict[str, str]) -> dict[str, str]:
    overrides = content.get("title_overrides") or {}
    return {key: overrides.get(key, value) for key, value in defaults.items()}
