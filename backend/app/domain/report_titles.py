"""Editorial heading overrides shared by the editor and all report renderers."""

from datetime import date
from typing import Any

from .localization import localized_portfolio_label, month_name, term
from .metrics.final_analytics import PORTFOLIO_METRIC_ORDER, normalize_portfolio_rows


TITLE_TERMS = (
    "historical_performance", "company_news", "constituent_performance",
    "top10", "sector_breakdown", "performers", "top_performers", "bottom_performers", "portfolio_analysis",
)
TITLE_KEYS = frozenset((*TITLE_TERMS, *(f"portfolio.{code}" for code in PORTFOLIO_METRIC_ORDER)))


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
