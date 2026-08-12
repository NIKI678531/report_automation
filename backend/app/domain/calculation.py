from calendar import monthrange
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
from typing import Iterable

from .validation import BLOCKING, FAILED, PASSED, WARNING

SECTOR_CHART_FORMULA_VERSION = "sector-weight-v1"

# The versioned display_format_profile from the rules document §6. Values are rounded
# ROUND_HALF_UP at the presentation boundary only; `raw_value` keeps full precision and a
# `display_value` never flows back into a calculation.
DISPLAY_FORMAT_V1 = {
    "sector_weight_places": 1,
    "aum_million_places": 2,
    "turnover_million_places": 0,
}

# Versioned template configuration, keyed by `formula_profile` (rules document §4.3: "legend
# order and colour come from versioned template configuration, not from database order or a
# hard-coded calculation"). Declaring the order keeps the legend stable month to month instead
# of reshuffling whenever two industries swap rank. The reference output orders the HSTECH
# breakdown Consumer Discretionary -> Information Technology -> Healthcare -> Industrials,
# which is *not* weight-descending: Information Technology carries the larger weight.
# Industries outside the list fall back to weight-descending with an ascending-code
# tie-breaker (SORT-001), so a newly mapped industry still lands somewhere deterministic.
INDUSTRY_DISPLAY_ORDER = {
    "hstech-2026.1": ["23", "70", "28", "10"],
}


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


def sector_breakdown(rows: Iterable[dict], display_order: list[str] | None = None) -> list[dict]:
    """Aggregate constituent weight by effective top-level industry.

    ``display_order`` is the versioned template configuration; industries it does not name are
    ranked weight-descending with an ascending-code tie-breaker (SORT-001). Order used to fall
    out of ``sorted(totals.items())``, which sorted by HSICS code and produced a legend the
    reference output does not use.

    Only the report-date-effective mapping is accepted. A raw source ``sector`` string used to
    satisfy this function, which meant a chart could be aggregated on a taxonomy assignment that
    QC-003 had already refused.
    """
    ranking = list(display_order or [])
    totals: dict[tuple[str, str], Decimal] = {}
    for row in rows:
        code = str(row.get("effective_industry_code") or "")
        label = str(row.get("effective_industry_name") or "")
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
    def rank(item: tuple[tuple[str, str], Decimal]) -> tuple[int, int, Decimal, str]:
        code = item[0][0]
        configured = ranking.index(code) if code in ranking else len(ranking)
        return (0 if code in ranking else 1, configured, -item[1], code)

    return [
        {"code": key[0], "sector": key[1], "weight": str(value)}
        for key, value in sorted(totals.items(), key=rank)
    ]


def sector_chart_snapshot(sectors: list[dict], payload: dict | None = None) -> dict:
    """The `industry_breakdown` chart snapshot defined by the rules document §4.3.

    Structured data, never a screenshot. Every value a renderer needs is resolved here:
    ordering, the zero-weight filter, the display string and a stable colour token. The
    renderer only lays the series out — it must not regroup, re-sort or recompute.
    """
    payload = payload or {}
    master = payload.get("industry_master") or {}
    places = DISPLAY_FORMAT_V1["sector_weight_places"]
    # Zero-weight industries never reach the chart (rules document §4.3). This filter used to
    # live in the renderer, where HTML and DOCX each applied their own version of it.
    positive = [row for row in sectors if Decimal(str(row["weight"])) > 0]
    source = json.dumps(sectors, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    snapshot = {
        "schema_version": 2,
        "chart_code": "industry_breakdown",
        "chart_type": "donut",
        "snapshot_id": str(payload.get("snapshot_id") or ""),
        "snapshot_dataset_ids": _chart_dataset_ids(payload),
        "formula_version": str(payload.get("formula_version") or SECTOR_CHART_FORMULA_VERSION),
        "mapping_version": str(payload.get("mapping_version") or ""),
        "taxonomy": str(master.get("taxonomy") or ""),
        "taxonomy_version": str(master.get("version") or ""),
        "as_of_date": str(payload.get("as_of_date") or ""),
        "series": [],
        "input_checksum": hashlib.sha256(source.encode("utf-8")).hexdigest(),
        "alt_text": "",
    }
    total = sum((Decimal(str(row["weight"])) for row in positive), Decimal("0"))
    if total <= 0:
        return snapshot

    cursor = Decimal("0")
    for index, row in enumerate(positive):
        weight = Decimal(str(row["weight"]))
        code = str(row.get("code") or row.get("sector") or "")
        start = cursor
        cursor += weight / total * Decimal("360")
        end = Decimal("360") if index == len(positive) - 1 else cursor
        snapshot["series"].append({
            "code": code,
            "label": str(row.get("sector") or ""),
            "raw_value": str(weight),
            "unit": "RATIO",
            "display_value": f"{display_percent(weight, places)}%",
            "sort_order": index + 1,
            # Bound to the industry, not to the position in the list. A positional index made
            # an industry change colour whenever the constituent set changed.
            "color_token": f"industry.hsics.{code}",
            "start_angle": str(start),
            "end_angle": str(end),
        })
    summary = ", ".join(f"{row['label']} {row['display_value']}" for row in snapshot["series"])
    snapshot["alt_text"] = f"Index sector breakdown: {summary}"
    return snapshot


def _chart_dataset_ids(payload: dict) -> list[str]:
    """Persisted SnapshotDataset ids behind the chart, when the caller knows them.

    ``calculate_snapshot`` stays free of database access, so ``run_calculation`` seeds
    ``snapshot_dataset_ids`` on the payload. Direct callers get the logical types instead of a
    fabricated id.
    """
    known = payload.get("snapshot_dataset_ids") or {}
    return sorted(
        str(known.get(dataset_type) or dataset_type)
        for dataset_type in ("constituent_snapshot", "industry_master")
    )


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
    """Deterministic quality gate for a composed snapshot payload.

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
    # Only real `ingestion.REGISTRY` slots. "constituents" and "final_analytics" used to be
    # listed here as well; neither has ever been a dataset type, so they could never match.
    for dataset_type in ("constituent_performance", "index_constituents"):
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
    sectors = sector_breakdown(rows, INDUSTRY_DISPLAY_ORDER.get(str(payload.get("formula_version") or "")))
    sector_chart = sector_chart_snapshot(sectors, payload)
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
            places = DISPLAY_FORMAT_V1["aum_million_places"]
            portfolio.append({"label": f"Asset Under Management ({row['currency']})^", "value": f"{Decimal(str(row['value'])):,.{places}f} {row['unit']}"})
        if turnover_rows:
            row = turnover_rows[-1]
            # §6: the turnover million value carries no decimals. It used to reuse the AUM
            # format and printed "12,882.00 million" where the reference prints "12,882 million".
            places = DISPLAY_FORMAT_V1["turnover_million_places"]
            rounded = turnover_average.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
            portfolio.append({"label": f"Average Daily Turnover ({row['currency']})^^", "value": f"{rounded:,.{places}f} {row['unit']}"})
        portfolio.append({"label": "Number of holdings", "value": str(sum(1 for row in rows if Decimal(str(row["weight"])) > 0))})
    else:
        # Only what the constituent set alone can support. This used to fall back to
        # `payload["analytics"]["portfolio"]` — copying a pre-formatted answer out of the input and
        # presenting it as a calculated result. `fund_kpi_daily` is a required slot, so a snapshot
        # without it is already incomplete and reports the gap as SNAPSHOT_INCOMPLETE; the missing
        # AUM and turnover rows now simply do not appear.
        portfolio = [
            {"label": "Number of holdings", "value": str(sum(1 for row in rows if Decimal(str(row["weight"])) > 0))}
        ]
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
