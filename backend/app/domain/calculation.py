from calendar import monthrange
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
from typing import Iterable

from .validation import BLOCKING, FAILED, PASSED, WARNING


class CalculationError(ValueError):
    """A deterministic calculation cannot proceed because its inputs are incomplete.

    Mirrors ``document.DocumentValidationError`` so the API layer can turn a domain failure into
    the ``error_code / field / entity_id / message / severity / fix_hint`` envelope instead of a
    bare 500. Subclasses ``ValueError`` so existing ``except ValueError`` callers keep working.
    """

    def __init__(self, error_code: str, message: str, field: str, fix_hint: str, entity_id: str | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.field = field
        self.entity_id = entity_id
        self.fix_hint = fix_hint


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


def display_percent(value: Decimal | float | int | None, places: int = 2) -> str:
    if value is None:
        return "N/A"
    quant = Decimal(1).scaleb(-places)
    return str((Decimal(str(value)) * Decimal("100")).quantize(quant, rounding=ROUND_HALF_UP))


def stable_rank(rows: Iterable[dict], key: str, descending: bool = True) -> list[dict]:
    return sorted(rows, key=lambda row: ((-Decimal(str(row[key]))) if descending else Decimal(str(row[key])), str(row.get("security_code", ""))))


def sector_breakdown(rows: Iterable[dict]) -> list[dict]:
    totals: dict[tuple[str, str], Decimal] = {}
    for row in rows:
        code = str(row.get("effective_industry_code") or row.get("sector") or "")
        label = str(row.get("effective_industry_name") or row.get("sector") or "")
        if not code or not label:
            raise CalculationError(
                "INDUSTRY_MAPPING_MISSING",
                f"Security {row.get('security_code')} has no effective industry mapping to aggregate by.",
                "constituents.effective_industry_code",
                "Import the report-date HSICS master, or correct the source industry code on this security.",
                str(row.get("security_code") or ""),
            )
        key = (code, label)
        totals[key] = totals.get(key, Decimal("0")) + Decimal(str(row["weight"]))
    return [{"code": key[0], "sector": key[1], "weight": str(value)} for key, value in sorted(totals.items())]


def sector_chart_snapshot(sectors: list[dict]) -> dict:
    total = sum((Decimal(str(row["weight"])) for row in sectors), Decimal("0"))
    if total <= 0:
        return {"schema_version": 1, "chart_type": "donut", "slices": [], "input_checksum": hashlib.sha256(b"[]").hexdigest()}
    cursor = Decimal("0")
    slices = []
    for index, row in enumerate(sectors):
        start = cursor
        cursor += Decimal(str(row["weight"])) / total * Decimal("360")
        end = Decimal("360") if index == len(sectors) - 1 else cursor
        slices.append({
            "code": str(row.get("code") or row.get("sector") or ""),
            "label": str(row.get("sector") or ""),
            "weight": str(row["weight"]),
            "start_angle": str(start),
            "end_angle": str(end),
            "color_index": index,
        })
    source = json.dumps(sectors, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return {
        "schema_version": 1,
        "chart_type": "donut",
        "slices": slices,
        "input_checksum": hashlib.sha256(source.encode("utf-8")).hexdigest(),
    }


def trading_days(payload: dict) -> set[str]:
    """The authoritative trading dates for the snapshot.

    KPI-002 and the turnover metrics both derive from this one set. They used to compute it
    separately, which let the quality check and the persisted coverage metric disagree.
    """
    return {
        str(row.get("date")) for row in payload.get("trading_calendar", [])
        if row.get("is_trading_day") is True
    }


def _aum_rows(fund_kpis: Iterable[dict], as_of_date: str) -> list[dict]:
    return [
        row for row in fund_kpis
        if row.get("metric_code") == "AUM" and str(row.get("metric_date")) == as_of_date
    ]


def _turnover_rows(fund_kpis: Iterable[dict], expected_days: set[str]) -> list[dict]:
    return [
        row for row in fund_kpis
        if row.get("metric_code") == "DAILY_TURNOVER" and str(row.get("metric_date")) in expected_days
    ]


def _turnover_days(fund_kpis: Iterable[dict], expected_days: set[str]) -> set[str]:
    return {str(row.get("metric_date")) for row in _turnover_rows(fund_kpis, expected_days)}


def quality_checks(payload: dict, expected_constituent_count: int | None = None) -> list[dict]:
    """Deterministic snapshot quality gate.

    Returns the canonical finding shape declared in ``validation.py`` (``check_id / severity /
    status / message / fix_hint``) plus the ``actual`` and ``threshold`` evidence that makes a
    quality result reproducible. Callers must not invent a second shape.
    """
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
        aum_rows = _aum_rows(fund_kpis, as_of_date)
        aum_valid = len(aum_rows) == 1 and bool(aum_rows[0].get("currency")) and bool(aum_rows[0].get("unit"))
        checks.append({
            "check_id": "KPI-001",
            "passed": aum_valid,
            "message": "Exactly one AUM observation sits on the report date with currency and unit.",
            "actual": {"matching_rows": len(aum_rows), "as_of_date": as_of_date},
            "threshold": "exactly one report-date AUM row with currency and unit",
            "fix_hint": "Provide one AUM observation on the report effective date with explicit currency and unit.",
        })
        expected_days = trading_days(payload)
        observed_days = _turnover_days(fund_kpis, expected_days)
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


def build_lineage_footnotes(payload: dict, metrics: dict | None = None) -> dict[str, str]:
    footnotes = dict(payload.get("footnotes") or {})
    as_of_date = str(payload.get("as_of_date") or "")
    series = payload.get("total_return_series", [])
    periods = payload.get("historical_performance", {}).get("periods", {})
    if series and periods:
        sources = ", ".join(sorted({str(row.get("source")) for row in series if row.get("source")}))
        period_labels = []
        for field, label in (("return_1m", "1M"), ("return_3m", "3M"), ("return_6m", "6M"), ("return_ytd", "YTD")):
            period = periods.get(field, {})
            if period.get("period_start") and period.get("period_end"):
                period_labels.append(f"{label} {period['period_start']} to {period['period_end']}")
        footnotes["historical"] = f"Source: {sources}; official Total Return series. {'; '.join(period_labels)}."

    datasets = payload.get("datasets", {})
    constituent_sources = []
    for dataset_type in ("constituent_performance", "index_constituents", "constituents", "final_analytics"):
        source = datasets.get(dataset_type)
        if isinstance(source, dict):
            constituent_sources.append(str(source.get("filename") or source.get("import_id") or dataset_type))
    if constituent_sources:
        taxonomy = payload.get("industry_master") or {}
        taxonomy_text = (
            f" HSICS {taxonomy.get('version')}." if taxonomy.get("version") else ""
        )
        footnotes["constituents"] = (
            f"Source: {', '.join(sorted(set(constituent_sources)))}; as of {as_of_date}."
            f"{taxonomy_text} Prices, weights and returns retain their source units and periods."
        )

    fund_kpis = payload.get("fund_kpis", [])
    if fund_kpis:
        sources = ", ".join(sorted({str(row.get("source")) for row in fund_kpis if row.get("source")}))
        metric_values = metrics or {}
        observed = metric_values.get("turnover_observation_count", 0)
        expected = metric_values.get("turnover_expected_day_count", 0)
        coverage = metric_values.get("turnover_coverage")
        coverage_text = f" turnover coverage {observed}/{expected} ({Decimal(str(coverage)) * Decimal('100'):.2f}%)" if coverage is not None else ""
        taxonomy = payload.get("industry_master") or {}
        taxonomy_text = f" Industry aggregation uses HSICS {taxonomy.get('version')}." if taxonomy.get("version") else ""
        footnotes["analytics"] = (
            f"Source: {sources}; AUM as of {as_of_date};{coverage_text}."
            f"{taxonomy_text} Number of holdings counts unique positive-weight securities."
        )
    return footnotes


def calculate_snapshot(payload: dict) -> tuple[dict, dict]:
    rows = payload.get("constituents", [])
    ranked_weight = sorted(rows, key=lambda row: (-Decimal(str(row["weight"])), str(row["security_code"])))
    ranked_return = sorted(
        (row for row in rows if row.get("return_1m") is not None),
        key=lambda row: (-Decimal(str(row["return_1m"])), -Decimal(str(row["weight"])), str(row["security_code"])),
    )
    bottom_selected = sorted(
        (row for row in rows if row.get("return_1m") is not None),
        key=lambda row: (Decimal(str(row["return_1m"])), -Decimal(str(row["weight"])), str(row["security_code"])),
    )[:3]
    bottom_display = sorted(
        bottom_selected,
        key=lambda row: (-Decimal(str(row["return_1m"])), -Decimal(str(row["weight"])), str(row["security_code"])),
    )
    sectors = sector_breakdown(rows)
    sector_chart = sector_chart_snapshot(sectors)
    # Derived once, above the `if fund_kpis:` branch. These used to be bound only inside that
    # branch while the metrics block below read them unconditionally, so any snapshot carrying a
    # trading calendar but no fund KPIs raised UnboundLocalError instead of reporting 0 coverage.
    as_of_date = str(payload.get("as_of_date") or "")
    fund_kpis = payload.get("fund_kpis", [])
    expected_days = trading_days(payload)
    aum_rows = _aum_rows(fund_kpis, as_of_date)
    turnover_rows = _turnover_rows(fund_kpis, expected_days)
    turnover_days = _turnover_days(fund_kpis, expected_days)
    turnover_average = (
        sum((Decimal(str(row["value"])) for row in turnover_rows), Decimal("0")) / Decimal(len(turnover_rows))
        if turnover_rows else None
    )
    if fund_kpis:
        portfolio = []
        if aum_rows:
            row = aum_rows[0]
            portfolio.append({"label": f"Asset Under Management ({row['currency']})^", "value": f"{Decimal(str(row['value'])):,.2f} {row['unit']}"})
        if turnover_rows:
            row = turnover_rows[-1]
            portfolio.append({"label": f"Average Daily Turnover ({row['currency']})^^", "value": f"{turnover_average:,.2f} {row['unit']}"})
        portfolio.append({"label": "Number of holdings", "value": str(sum(1 for row in rows if Decimal(str(row["weight"])) > 0))})
    else:
        portfolio = payload.get("analytics", {}).get("portfolio", [
            {"label": "Number of holdings", "value": str(sum(1 for row in rows if Decimal(str(row["weight"])) > 0))}
        ])
    analytics = {
        "top10": [{"issuer": row["name_en"], "weight": row["weight"], "security_code": row["security_code"]} for row in ranked_weight[:10]],
        "sectors": sectors,
        "sector_chart": sector_chart,
        "top": [{"issuer": row["name_en"], "return": row["return_1m"], "security_code": row["security_code"]} for row in ranked_return[:3]],
        "bottom": [{"issuer": row["name_en"], "return": row["return_1m"], "security_code": row["security_code"]} for row in bottom_display],
        "portfolio": portfolio,
    }
    expected_day_count = len(expected_days)
    constituent_index_code = str(payload.get("constituent_index_code") or "")
    future_rebalances = sorted(
        str(row["effective_date"])
        for row in payload.get("index_events", [])
        if row.get("event_type") == "REBALANCE"
        and str(row.get("index_code") or "") == constituent_index_code
        and str(row.get("effective_date") or "") > as_of_date
    )
    metrics = {
        "constituent_count": len(rows),
        "weight_total": str(sum((Decimal(str(row["weight"])) for row in rows), Decimal("0"))),
        "sector_count": len(sectors),
        "top_security_code": ranked_return[0]["security_code"] if ranked_return else None,
        "bottom_security_code": bottom_selected[0]["security_code"] if bottom_selected else None,
        # Counted on the same basis as KPI-002 — distinct trading days observed — so the check,
        # the metric and the footnote can never quote three different numerators.
        "turnover_observation_count": len(turnover_days),
        "turnover_expected_day_count": expected_day_count,
        "turnover_average": str(turnover_average) if turnover_average is not None else None,
        "turnover_coverage": str(Decimal(len(turnover_days)) / Decimal(expected_day_count)) if expected_day_count else None,
        "aum_value": str(aum_rows[0]["value"]) if aum_rows else None,
        "next_rebalancing_date": future_rebalances[0] if future_rebalances else None,
    }
    return analytics, metrics
