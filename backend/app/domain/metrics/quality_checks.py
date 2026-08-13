"""The QC and KPI gate.

Not a report module — these checks span modules, so they belong to none of them. They return the
canonical finding shape declared in ``domain/validation.py`` (``check_id / severity / status /
message / fix_hint``) plus the ``actual`` and ``threshold`` evidence that makes a quality result
reproducible. Callers must not invent a second shape.
"""

from decimal import Decimal

from ..validation import BLOCKING, FAILED, PASSED, WARNING
from .fund_kpis import aum_rows, trading_days, turnover_days

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
    if fund_kpis:
        as_of_date = str(payload.get("as_of_date") or "")
        aum = aum_rows(fund_kpis, as_of_date)
        aum_valid = len(aum) == 1 and bool(aum[0].get("currency")) and bool(aum[0].get("unit"))
        checks.append({
            "check_id": "KPI-001",
            "passed": aum_valid,
            "message": "Exactly one AUM observation sits on the report date with currency and unit.",
            "actual": {"matching_rows": len(aum), "as_of_date": as_of_date},
            "threshold": "exactly one report-date AUM row with currency and unit",
            "fix_hint": "Provide one AUM observation on the report effective date with explicit currency and unit.",
        })
        expected_days = trading_days(payload)
        observed_days = turnover_days(fund_kpis, expected_days)
        coverage = Decimal(len(observed_days)) / Decimal(len(expected_days)) if expected_days else Decimal("0")
        checks.append({
            "check_id": "KPI-002",
            "passed": bool(expected_days) and coverage >= Decimal("0.95"),
            "message": "Daily turnover covers at least 95% of the authoritative trading days.",
            "actual": {
                "observed_days": len(observed_days),
                "expected_days": len(expected_days),
                "coverage": str(coverage),
            },
            "threshold": "coverage >= 0.95",
            "fix_hint": "Load the authoritative trading calendar and unique daily turnover observations covering at least 95% of trading days.",
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
