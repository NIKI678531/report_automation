"""Report module 02 — Historical Performance.

Period returns for the FUND and BENCHMARK legs, resolved against common observation dates in the
official Total Return series.
"""

from calendar import monthrange
from datetime import date
from decimal import Decimal

from .errors import CalculationError


def period_return(start: Decimal, end: Decimal) -> Decimal:
    if start <= 0:
        raise CalculationError(
            "TOTAL_RETURN_START_INVALID",
            "The total-return value at the period start must be greater than zero.",
            "total_return_series.total_return_value",
            "Correct the total-return series so every period start carries a positive value.",
        )
    return end / start - Decimal("1")


def _shift_months(value: date, months: int) -> date:
    month_index = value.year * 12 + value.month - 1 - months
    year, zero_based_month = divmod(month_index, 12)
    month = zero_based_month + 1
    source_month_end = value.day == monthrange(value.year, value.month)[1]
    target_day = monthrange(year, month)[1] if source_month_end else min(value.day, monthrange(year, month)[1])
    return date(year, month, target_day)


def historical_performance(series: list[dict], report_date: date, formula_version: str) -> dict:
    """Period returns for FUND and BENCHMARK.

    ``formula_version`` is supplied by the caller (the product catalogue's ``formula_profile``) so
    the version stamped on the result is the same one persisted on ``MetricValue`` and written into
    the document. The function must never invent its own version.
    """
    by_role: dict[str, dict[date, Decimal]] = {"FUND": {}, "BENCHMARK": {}}
    codes: dict[str, str] = {}
    for row in series:
        role = str(row["instrument_role"])
        trade_date = date.fromisoformat(str(row["trade_date"]))
        by_role[role][trade_date] = Decimal(str(row["total_return_value"]))
        codes[role] = str(row["instrument_code"])
    common_dates = sorted(
        item for item in set(by_role["FUND"]) & set(by_role["BENCHMARK"])
        if item <= report_date
    )
    if not common_dates:
        raise CalculationError(
            "HISTORICAL_PERIODS_INCOMPLETE",
            "FUND and BENCHMARK require at least one common date not later than the report date.",
            "total_return_series.trade_date",
            "Load a total-return series where both instruments are observed on the same dates.",
        )
    targets = {
        "return_1m": _shift_months(report_date, 1),
        "return_3m": _shift_months(report_date, 3),
        "return_6m": _shift_months(report_date, 6),
        "return_ytd": date(report_date.year - 1, 12, 31),
    }
    end_date = common_dates[-1]
    periods: dict[str, dict[str, str]] = {}
    starts: dict[str, date] = {}
    for key, target in targets.items():
        candidates = [item for item in common_dates if item <= target]
        if not candidates:
            raise CalculationError(
                "HISTORICAL_PERIODS_INCOMPLETE",
                f"The historical series has no common start point for {key}.",
                f"total_return_series.{key}",
                f"Extend the total-return series back to {target.isoformat()} for both instruments.",
                key,
            )
        starts[key] = candidates[-1]
        periods[key] = {"period_start": candidates[-1].isoformat(), "period_end": end_date.isoformat()}
    rows = []
    for role in ("FUND", "BENCHMARK"):
        item: dict[str, str] = {"role": role, "name": codes[role]}
        for key, start_date in starts.items():
            item[key] = str(period_return(by_role[role][start_date], by_role[role][end_date]))
        rows.append(item)
    return {"rows": rows, "periods": periods, "effective_as_of": end_date.isoformat(), "formula_version": formula_version}
