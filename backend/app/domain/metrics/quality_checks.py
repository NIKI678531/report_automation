"""The QC and KPI gate.

Not a report module — these checks span modules, so they belong to none of them. They return the
canonical finding shape declared in ``domain/validation.py`` (``check_id / severity / status /
message / fix_hint``) plus the ``actual`` and ``threshold`` evidence that makes a quality result
reproducible. Callers must not invent a second shape.
"""

from decimal import Decimal

from ..validation import BLOCKING, FAILED, PASSED, WARNING
from .fund_kpis import (
    amount_in_millions,
    aum_rows,
    common_currency,
    monthly_turnover_average_in_millions,
    monthly_turnover_rows,
    monthly_turnover_source_average_matches,
    trading_days,
    turnover_days,
    turnover_rows,
)

# Checks that are meaningful on a freshly parsed *single* dataset, before it is composed into a
# snapshot. Anything requiring cross-dataset context is deliberately absent: QC-003 needs the
# report-date industry master, QC-006/QC-007 need derived history and footnotes, and the KPI
# checks need the report date, so running them here would fail every honest upload.
IMPORT_CHECK_SETS = {
    "constituent_performance": ("QC-001", "QC-002", "QC-004"),
    "index_constituents": ("QC-001", "QC-002", "QC-004"),
    "total_return_series": ("QC-005",),
}


def import_checks(payload: dict, dataset_type: str) -> list[dict]:
    """Quality gate for one parsed upload, before it becomes part of a snapshot.

    Separated from :func:`snapshot_checks` because the two were being fed incompatible payload
    shapes through a single entry point: the import path passes a parsed single-dataset payload
    and the snapshot path passes the derived, composed payload. Sharing one function meant the
    import path silently skipped every check whose data was not present yet.
    """
    selected = IMPORT_CHECK_SETS.get(dataset_type)
    if not selected:
        return []
    return [item for item in snapshot_checks(payload) if item["check_id"] in selected]


def snapshot_checks(payload: dict, expected_constituent_count: int | None = None) -> list[dict]:
    """Deterministic quality gate for a composed snapshot payload."""
    rows = payload.get("constituents", [])
    results: list[dict] = []
    codes = [str(row.get("security_code", "")) for row in rows]
    weight = sum((Decimal(str(row.get("weight", 0))) for row in rows), Decimal("0"))
    checks: list[dict] = [
        {
            "check_id": "QC-001",
            "passed": bool(codes) and all(codes) and len(codes) == len(set(codes)),
            "message": "Constituent security codes are present and unique.",
            "actual": len(codes),
            "threshold": "index_code + as_of_date + security_code unique",
            "fix_hint": "Security codes must be present and unique within the effective constituent snapshot.",
        },
        {
            "check_id": "QC-002",
            "passed": abs(weight - Decimal("1")) <= Decimal("0.0001"),
            "message": "Constituent weights total 100%.",
            "actual": str(weight),
            "threshold": "1.0000 ± 0.0001",
            "fix_hint": "Weights must total 100% ± 0.01 percentage points before rounding.",
        },
        {
            # Only the report-date-effective mapping counts. A raw source sector name is lineage,
            # not an approved taxonomy assignment, so it must not satisfy this check.
            "check_id": "QC-003",
            "passed": bool(rows) and all(row.get("effective_industry_code") for row in rows),
            "message": "Every constituent carries a report-date-effective industry mapping.",
            "actual": sum(1 for row in rows if not row.get("effective_industry_code")),
            "threshold": 0,
            "fix_hint": "Every constituent requires a report-date-effective industry mapping.",
        },
    ]

    as_of_value = payload.get("as_of_date")
    dated_rows = [str(row.get("as_of_date")) for row in rows if row.get("as_of_date")]
    dates_consistent = not as_of_value or all(value <= str(as_of_value) for value in dated_rows)
    checks.append({
        "check_id": "QC-004",
        "passed": dates_consistent,
        "message": "No constituent carries a business date later than the snapshot date.",
        "actual": {"snapshot_as_of": as_of_value, "row_dates": sorted(set(dated_rows))},
        "threshold": "all business dates <= snapshot as_of date",
        "fix_hint": "Use records whose business date is not later than the report snapshot date.",
    })

    series = payload.get("total_return_series", [])
    history = payload.get("historical_performance", {}).get("rows", [])
    if series or history:
        series_types = {str(row.get("series_type", "")).replace("_", " ").upper() for row in series}
        currencies = {str(row.get("currency", "")).upper() for row in series if row.get("currency")}
        return_basis_valid = not series or (series_types == {"TOTAL RETURN"} and len(currencies) <= 1)
        checks.append({
            "check_id": "QC-005",
            "passed": return_basis_valid,
            "message": "The performance series is Total Return in a single currency.",
            "actual": {
                "source": "TOTAL_RETURN_SERIES" if series else "APPROVED_PERIOD_RETURN",
                "series_types": sorted(series_types),
                "currencies": sorted(currencies),
            },
            "threshold": "Total Return with comparable currency definition",
            "fix_hint": "Use official Total Return data, or an explicitly approved period-return dataset with lineage.",
        })
        period_fields = ("return_1m", "return_3m", "return_6m", "return_ytd")
        if history:
            complete = all(all(row.get(field) is not None for field in period_fields) for row in history)
            checks.append({
                "check_id": "QC-006",
                "passed": complete,
                "message": "Every required performance period resolved to a value.",
                "actual": {field: sum(1 for row in history if row.get(field) is not None) for field in period_fields},
                "threshold": {field: len(history) for field in period_fields},
                "fix_hint": "Each required period needs valid common endpoints; preserve N/A rather than substituting zero.",
            })

    footnotes = payload.get("footnotes")
    if footnotes:
        required_footnotes = {"historical", "constituents", "analytics"}
        missing_footnotes = sorted(key for key in required_footnotes if not footnotes.get(key))
        checks.append({
            "check_id": "QC-007",
            "passed": not missing_footnotes,
            "message": "Every data footnote was generated from its effective source.",
            "actual": {"missing": missing_footnotes},
            "threshold": {"required": sorted(required_footnotes)},
            "fix_hint": "Generate each data footnote from the effective source, date, period and formula lineage.",
        })

    fund_kpis = payload.get("fund_kpis", [])
    report_date = str(payload.get("report_date") or payload.get("as_of_date") or "")
    monthly_turnover = monthly_turnover_rows(payload, report_date)
    if fund_kpis or payload.get("fund_turnover_monthly"):
        product_currency = str(payload.get("product_currency") or "").strip().upper()
        aum = aum_rows(fund_kpis, report_date)
        aum_currency = common_currency(aum)
        aum_as_of_date = str(aum[0].get("metric_date")) if len(aum) == 1 else None
        aum_valid = (
            len(aum) == 1
            and aum_currency is not None
            and amount_in_millions(aum[0]) is not None
            and (not product_currency or aum_currency == product_currency)
        )
        checks.append({
            "check_id": "KPI-001",
            "passed": aum_valid,
            "message": "Exactly one convertible AUM observation sits on the latest valid report-month date.",
            "actual": {
                "matching_rows": len(aum),
                "report_date": report_date,
                "as_of_date": aum_as_of_date,
                "currency": aum_currency,
                "product_currency": product_currency or None,
                "unit": aum[0].get("unit") if len(aum) == 1 else None,
            },
            "threshold": "one latest same-month AUM row not later than report_date, with currency and a supported amount unit",
            "fix_hint": "Provide one AUM observation on or before the report date in the same month, using an explicit currency and supported unit.",
        })
        expected_days = trading_days(payload)
        observed_rows = turnover_rows(fund_kpis, expected_days)
        observed_days = turnover_days(fund_kpis, expected_days)
        uses_monthly_aggregate = not observed_rows and not expected_days and len(monthly_turnover) == 1
        source_conflict = bool(monthly_turnover) and bool(observed_rows or expected_days)
        if uses_monthly_aggregate:
            monthly_row = monthly_turnover[0]
            try:
                observed_count = int(monthly_row.get("trading_days"))
            except (TypeError, ValueError):
                observed_count = 0
            expected_count = observed_count
            coverage = Decimal("1") if observed_count > 0 else Decimal("0")
            duplicate_days = False
            turnover_currency = common_currency(monthly_turnover)
            units_valid = (
                monthly_turnover_average_in_millions(monthly_row) is not None
                and monthly_turnover_source_average_matches(monthly_row)
            )
        else:
            observed_count = len(observed_days)
            expected_count = len(expected_days)
            coverage = Decimal(observed_count) / Decimal(expected_count) if expected_count else Decimal("0")
            duplicate_days = len(observed_rows) != len(observed_days)
            turnover_currency = common_currency(observed_rows)
            units_valid = all(amount_in_millions(row) is not None for row in observed_rows)
        currency_matches_aum = not aum_currency or not turnover_currency or turnover_currency == aum_currency
        currency_matches_product = not product_currency or turnover_currency == product_currency
        checks.append({
            "check_id": "KPI-002",
            "passed": (
                expected_count > 0
                and coverage >= Decimal("0.95")
                and not duplicate_days
                and not source_conflict
                and turnover_currency is not None
                and units_valid
                and currency_matches_aum
                and currency_matches_product
            ),
            "message": "Turnover is unit-compatible and uses either complete Bloomberg monthly inputs or at least 95% daily coverage.",
            "actual": {
                "source_basis": "BLOOMBERG_INTERVAL_SUM_DIV_TRADING_DAYS" if uses_monthly_aggregate else "DAILY_OBSERVATIONS",
                "observed_days": observed_count,
                "expected_days": expected_count,
                "coverage": str(coverage),
                "duplicate_days": duplicate_days,
                "source_conflict": source_conflict,
                "currency": turnover_currency,
                "units": sorted({str(row.get("unit") or "") for row in (monthly_turnover if uses_monthly_aggregate else observed_rows)}),
                "currency_matches_aum": currency_matches_aum,
                "currency_matches_product": currency_matches_product,
            },
            "threshold": "one exact-period monthly INTERVAL_SUM/trading-days row, or daily coverage >= 0.95, in the AUM currency",
            "fix_hint": "Load one valid Bloomberg monthly turnover record or unique daily turnover observations in the AUM currency.",
        })
        if not uses_monthly_aggregate and Decimal("0.95") <= coverage < Decimal("1"):
            checks.append({
                "check_id": "KPI-002-PARTIAL-COVERAGE",
                "passed": False,
                "severity": WARNING,
                "message": "Daily turnover passes the release threshold but does not cover every trading day.",
                "actual": {
                    "observed_days": len(observed_days),
                    "expected_days": len(expected_days),
                    "coverage": str(coverage),
                },
                "threshold": "coverage = 1 for a warning-free result",
                "fix_hint": "Load the missing daily-turnover observations or disclose the partial coverage.",
            })

    if expected_constituent_count is not None:
        checks.append({
            "check_id": "QC-HOLDING-COUNT",
            "passed": len(rows) == expected_constituent_count,
            "message": "The positive-weight holding count matches the product profile.",
            "actual": len(rows),
            "threshold": expected_constituent_count,
            "severity": WARNING,
            "fix_hint": "Compare the actual positive-weight holding count with the product profile expectation.",
        })
    for item in checks:
        results.append({
            "check_id": item["check_id"],
            "severity": item.get("severity", BLOCKING),
            "status": PASSED if item["passed"] else FAILED,
            "message": item["message"],
            "actual": item["actual"],
            "threshold": item.get("threshold"),
            "fix_hint": item["fix_hint"],
        })
    return results
