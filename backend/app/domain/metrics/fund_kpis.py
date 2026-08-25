"""Readers over the fund KPI and trading-calendar slots.

Not a report module. These sit here because :mod:`.final_analytics` and :mod:`.quality_checks`
both derive from them: KPI-002 and the persisted turnover metrics used to compute the trading-day
set separately, which let the quality check and the metric quote different numerators.
"""

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Iterable


DISPLAY_AMOUNT_UNIT = "million"
_AMOUNT_UNIT_TO_BASE = {
    "1": Decimal("1"),
    "one": Decimal("1"),
    "unit": Decimal("1"),
    "units": Decimal("1"),
    "k": Decimal("1000"),
    "thousand": Decimal("1000"),
    "thousands": Decimal("1000"),
    "m": Decimal("1000000"),
    "mn": Decimal("1000000"),
    "million": Decimal("1000000"),
    "millions": Decimal("1000000"),
    "b": Decimal("1000000000"),
    "bn": Decimal("1000000000"),
    "billion": Decimal("1000000000"),
    "billions": Decimal("1000000000"),
}


def trading_days(payload: dict) -> set[str]:
    """The authoritative trading dates for the snapshot."""
    return {
        str(row.get("date")) for row in payload.get("trading_calendar", [])
        if row.get("is_trading_day") is True
    }


def aum_rows(fund_kpis: Iterable[dict], report_date: str) -> list[dict]:
    """Return AUM rows on the latest same-month date not later than the report date.

    Returning every row on that selected date deliberately preserves duplicate detection in the
    quality gate instead of silently choosing one source record.
    """
    try:
        cutoff = date.fromisoformat(report_date)
    except (TypeError, ValueError):
        return []
    eligible: list[tuple[date, dict]] = []
    for row in fund_kpis:
        if row.get("metric_code") != "AUM":
            continue
        try:
            metric_date = date.fromisoformat(str(row.get("metric_date")))
        except ValueError:
            continue
        if metric_date <= cutoff and (metric_date.year, metric_date.month) == (cutoff.year, cutoff.month):
            eligible.append((metric_date, row))
    if not eligible:
        return []
    selected_date = max(metric_date for metric_date, _ in eligible)
    return [row for metric_date, row in eligible if metric_date == selected_date]


def turnover_rows(fund_kpis: Iterable[dict], expected_days: set[str]) -> list[dict]:
    return sorted([
        row for row in fund_kpis
        if row.get("metric_code") == "DAILY_TURNOVER" and str(row.get("metric_date")) in expected_days
    ], key=lambda row: str(row.get("metric_date") or ""))


def turnover_days(fund_kpis: Iterable[dict], expected_days: set[str]) -> set[str]:
    return {str(row.get("metric_date")) for row in turnover_rows(fund_kpis, expected_days)}


def amount_in_millions(row: dict) -> Decimal | None:
    """Convert an explicitly-unitized amount to the report's million display unit.

    The source value is never guessed: an unknown/missing unit or malformed value returns
    ``None`` and is rejected by the KPI quality gate. This also prevents a value already supplied
    in millions from being divided by one million a second time.
    """
    unit = str(row.get("unit") or "").strip().lower()
    multiplier = _AMOUNT_UNIT_TO_BASE.get(unit)
    if multiplier is None:
        return None
    try:
        value = Decimal(str(row.get("value")))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not value.is_finite() or value < 0:
        return None
    return value * multiplier / _AMOUNT_UNIT_TO_BASE[DISPLAY_AMOUNT_UNIT]


def common_currency(rows: Iterable[dict]) -> str | None:
    """Return the one explicit currency shared by all rows, otherwise ``None``."""
    currencies = {str(row.get("currency") or "").strip().upper() for row in rows}
    return next(iter(currencies)) if len(currencies) == 1 and "" not in currencies else None
