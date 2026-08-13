"""Readers over the fund KPI and trading-calendar slots.

Not a report module. These sit here because :mod:`.final_analytics` and :mod:`.quality_checks`
both derive from them: KPI-002 and the persisted turnover metrics used to compute the trading-day
set separately, which let the quality check and the metric quote different numerators.
"""

from typing import Iterable


def trading_days(payload: dict) -> set[str]:
    """The authoritative trading dates for the snapshot."""
    return {
        str(row.get("date")) for row in payload.get("trading_calendar", [])
        if row.get("is_trading_day") is True
    }


def aum_rows(fund_kpis: Iterable[dict], as_of_date: str) -> list[dict]:
    return [
        row for row in fund_kpis
        if row.get("metric_code") == "AUM" and str(row.get("metric_date")) == as_of_date
    ]


def turnover_rows(fund_kpis: Iterable[dict], expected_days: set[str]) -> list[dict]:
    return [
        row for row in fund_kpis
        if row.get("metric_code") == "DAILY_TURNOVER" and str(row.get("metric_date")) in expected_days
    ]


def turnover_days(fund_kpis: Iterable[dict], expected_days: set[str]) -> set[str]:
    return {str(row.get("metric_date")) for row in turnover_rows(fund_kpis, expected_days)}
