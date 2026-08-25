"""Report module 05 — Final Analytics, and the summary metrics that support it.

:func:`calculate_snapshot` is the one entry point the orchestration layer calls. It returns the
Final Analytics payload (Top 10 holdings, the industry breakdown and its chart, top and bottom
performers, the portfolio block) alongside the flat ``metrics`` dict that becomes ``MetricValue``
rows. The rankings come from :mod:`.constituent_performance` and the donut from
:mod:`.industry_breakdown`; nothing is recomputed here.
"""

from decimal import Decimal, ROUND_HALF_UP

from .constituent_performance import (
    bottom_by_return,
    next_rebalancing_date,
    positive_weight_count,
    rank_by_return,
    rank_by_weight,
)
from .formatting import DISPLAY_FORMAT_V1
from .fund_kpis import (
    DISPLAY_AMOUNT_UNIT,
    amount_in_millions,
    aum_rows,
    common_currency,
    trading_days,
    turnover_days,
    turnover_rows,
)
from .industry_breakdown import INDUSTRY_DISPLAY_ORDER, sector_breakdown, sector_chart_snapshot


PORTFOLIO_METRIC_ORDER = ("AUM", "AVERAGE_DAILY_TURNOVER", "NUMBER_OF_HOLDINGS")


def normalize_portfolio_rows(portfolio: object, currency: str = "HKD") -> list[dict]:
    """Return the fixed three-row Portfolio Analysis presentation contract.

    Older and partially calculated documents may contain only the holding count. Renderers must
    still show the two fund KPI rows so users can distinguish missing source data from a missing
    feature. A missing amount is represented as ``N/A``; no financial value is inferred.
    """
    source = [dict(row) for row in portfolio if isinstance(row, dict)] if isinstance(portfolio, list) else []
    resolved_currency = str(currency or "HKD").strip().upper() or "HKD"
    for row in source:
        row_currency = str(row.get("currency") or "").strip().upper()
        if row_currency:
            resolved_currency = row_currency
            break

    def code_of(row: dict) -> str | None:
        code = str(row.get("metric_code") or "").strip().upper()
        if code in PORTFOLIO_METRIC_ORDER:
            return code
        label = str(row.get("label") or "").strip().lower()
        if label.startswith("asset under management"):
            return "AUM"
        if label.startswith("average daily turnover"):
            return "AVERAGE_DAILY_TURNOVER"
        if label == "number of holdings":
            return "NUMBER_OF_HOLDINGS"
        return None

    by_code = {code: row for row in source if (code := code_of(row)) is not None}
    specifications = (
        ("AUM", f"Asset Under Management ({resolved_currency})^", DISPLAY_FORMAT_V1["aum_million_places"], DISPLAY_AMOUNT_UNIT),
        ("AVERAGE_DAILY_TURNOVER", f"Average Daily Turnover ({resolved_currency})^^", DISPLAY_FORMAT_V1["turnover_million_places"], DISPLAY_AMOUNT_UNIT),
        ("NUMBER_OF_HOLDINGS", "Number of holdings", 0, "count"),
    )
    normalized: list[dict] = []
    for code, label, precision, unit in specifications:
        candidate = by_code.get(code)
        row = {
            "metric_code": code,
            "label": label,
            "raw_value": None,
            "unit": unit,
            "display_precision": precision,
            "display_value": "N/A",
            "value": "N/A",
            "availability": "MISSING_SOURCE_DATA",
        }
        if code != "NUMBER_OF_HOLDINGS":
            row["currency"] = resolved_currency
        if candidate:
            row.update(candidate)
            row["metric_code"] = code
            row["label"] = label
            display_value = candidate.get("display_value") or candidate.get("value") or "N/A"
            row["display_value"] = str(display_value)
            row["value"] = str(display_value)
            if display_value != "N/A":
                row.pop("availability", None)
            else:
                row["availability"] = "MISSING_SOURCE_DATA"
        normalized.append(row)
    return normalized


def calculate_snapshot(payload: dict) -> tuple[dict, dict]:
    rows = payload.get("constituents", [])
    ranked_weight = rank_by_weight(rows)
    ranked_return = rank_by_return(rows)
    bottom_selected = bottom_by_return(rows)
    sectors = sector_breakdown(rows, INDUSTRY_DISPLAY_ORDER.get(str(payload.get("formula_version") or "")))
    sector_chart = sector_chart_snapshot(sectors, payload)
    # Derived once, above the `if fund_kpis:` branch. These used to be bound only inside that
    # branch while the metrics block below read them unconditionally, so any snapshot carrying a
    # trading calendar but no fund KPIs raised UnboundLocalError instead of reporting 0 coverage.
    as_of_date = str(payload.get("as_of_date") or "")
    report_date = str(payload.get("report_date") or as_of_date)
    fund_kpis = payload.get("fund_kpis", [])
    expected_days = trading_days(payload)
    aum = aum_rows(fund_kpis, report_date)
    turnover = turnover_rows(fund_kpis, expected_days)
    observed_turnover_days = turnover_days(fund_kpis, expected_days)
    aum_row = aum[0] if len(aum) == 1 else None
    aum_as_of_date = str(aum_row.get("metric_date")) if aum_row else None
    aum_value = amount_in_millions(aum_row) if aum_row else None
    aum_currency = common_currency([aum_row]) if aum_row else None
    turnover_currency = common_currency(turnover)
    turnover_values = [amount_in_millions(row) for row in turnover]
    unique_turnover_dates = len(observed_turnover_days) == len(turnover)
    turnover_average = (
        sum((value for value in turnover_values if value is not None), Decimal("0")) / Decimal(len(turnover_values))
        if turnover_values
        and unique_turnover_dates
        and turnover_currency
        and all(value is not None for value in turnover_values)
        else None
    )
    portfolio = []
    if aum_value is not None and aum_currency:
        places = DISPLAY_FORMAT_V1["aum_million_places"]
        rounded = aum_value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
        display_value = f"{rounded:,.{places}f} {DISPLAY_AMOUNT_UNIT}"
        portfolio.append({
            "metric_code": "AUM",
            "label": f"Asset Under Management ({aum_currency})^",
            "raw_value": format(aum_value, "f"),
            "currency": aum_currency,
            "unit": DISPLAY_AMOUNT_UNIT,
            "display_precision": places,
            "display_value": display_value,
            "value": display_value,
            "as_of_date": aum_as_of_date,
        })
    if turnover_average is not None and turnover_currency:
        # The turnover million value carries no decimals; it must not reuse the two-decimal AUM
        # presentation profile.
        places = DISPLAY_FORMAT_V1["turnover_million_places"]
        rounded = turnover_average.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
        display_value = f"{rounded:,.{places}f} {DISPLAY_AMOUNT_UNIT}"
        coverage = (
            Decimal(len(observed_turnover_days)) / Decimal(len(expected_days))
            if expected_days else None
        )
        portfolio.append({
            "metric_code": "AVERAGE_DAILY_TURNOVER",
            "label": f"Average Daily Turnover ({turnover_currency})^^",
            "raw_value": format(turnover_average, "f"),
            "currency": turnover_currency,
            "unit": DISPLAY_AMOUNT_UNIT,
            "display_precision": places,
            "display_value": display_value,
            "value": display_value,
            "as_of_date": max(observed_turnover_days) if observed_turnover_days else None,
            "observation_count": len(observed_turnover_days),
            "expected_day_count": len(expected_days),
            "coverage": format(coverage, "f") if coverage is not None else None,
            "is_provisional": coverage is not None and coverage < Decimal("1"),
        })
    holding_count = positive_weight_count(rows)
    portfolio.append({
        "metric_code": "NUMBER_OF_HOLDINGS",
        "label": "Number of holdings",
        "raw_value": str(holding_count),
        "unit": "count",
        "display_precision": 0,
        "display_value": str(holding_count),
        "value": str(holding_count),
    })
    portfolio = normalize_portfolio_rows(portfolio, str(payload.get("product_currency") or "HKD"))
    def issuer_row(row: dict, value_key: str) -> dict:
        return {
            "issuer": row.get("name_en") or "",
            "issuer_zh_hans": row.get("name_zh_hans") or "",
            "issuer_zh_hant": row.get("name_zh_hant") or "",
            value_key: row[value_key],
            "security_code": row["security_code"],
            "name_zh_hans_source": row.get("name_zh_hans_source", "MISSING"),
        }

    analytics = {
        "top10": [issuer_row(row, "weight") for row in ranked_weight[:10]],
        "sectors": sectors,
        "sector_chart": sector_chart,
        "top": [issuer_row({**row, "return": row["return_1m"]}, "return") for row in ranked_return[:3]],
        "bottom": [issuer_row({**row, "return": row["return_1m"]}, "return") for row in bottom_selected],
        "portfolio": portfolio,
    }
    expected_day_count = len(expected_days)
    metrics = {
        "constituent_count": len(rows),
        "weight_total": str(sum((Decimal(str(row["weight"])) for row in rows), Decimal("0"))),
        "sector_count": len(sectors),
        "top_security_code": ranked_return[0]["security_code"] if ranked_return else None,
        "bottom_security_code": bottom_selected[0]["security_code"] if bottom_selected else None,
        # Counted on the same basis as KPI-002 — distinct trading days observed — so the check,
        # the metric and the footnote can never quote three different numerators.
        "turnover_observation_count": len(observed_turnover_days),
        "turnover_expected_day_count": expected_day_count,
        "turnover_average": format(turnover_average, "f") if turnover_average is not None else None,
        "turnover_currency": turnover_currency if turnover_average is not None else None,
        "turnover_unit": DISPLAY_AMOUNT_UNIT if turnover_average is not None else None,
        "turnover_coverage": str(Decimal(len(observed_turnover_days)) / Decimal(expected_day_count)) if expected_day_count else None,
        "aum_value": format(aum_value, "f") if aum_value is not None else None,
        "aum_currency": aum_currency if aum_value is not None else None,
        "aum_unit": DISPLAY_AMOUNT_UNIT if aum_value is not None else None,
        "aum_as_of_date": aum_as_of_date if aum_value is not None else None,
        "next_rebalancing_date": next_rebalancing_date(payload, as_of_date),
    }
    return analytics, metrics
