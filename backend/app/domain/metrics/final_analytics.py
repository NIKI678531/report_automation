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
    order_for_display,
    positive_weight_count,
    rank_by_return,
    rank_by_weight,
)
from .formatting import DISPLAY_FORMAT_V1
from .fund_kpis import aum_rows, trading_days, turnover_days, turnover_rows
from .industry_breakdown import INDUSTRY_DISPLAY_ORDER, sector_breakdown, sector_chart_snapshot


def calculate_snapshot(payload: dict) -> tuple[dict, dict]:
    rows = payload.get("constituents", [])
    ranked_weight = rank_by_weight(rows)
    ranked_return = rank_by_return(rows)
    bottom_selected = bottom_by_return(rows)
    bottom_display = order_for_display(bottom_selected)
    sectors = sector_breakdown(rows, INDUSTRY_DISPLAY_ORDER.get(str(payload.get("formula_version") or "")))
    sector_chart = sector_chart_snapshot(sectors, payload)
    # Derived once, above the `if fund_kpis:` branch. These used to be bound only inside that
    # branch while the metrics block below read them unconditionally, so any snapshot carrying a
    # trading calendar but no fund KPIs raised UnboundLocalError instead of reporting 0 coverage.
    as_of_date = str(payload.get("as_of_date") or "")
    fund_kpis = payload.get("fund_kpis", [])
    expected_days = trading_days(payload)
    aum = aum_rows(fund_kpis, as_of_date)
    turnover = turnover_rows(fund_kpis, expected_days)
    observed_turnover_days = turnover_days(fund_kpis, expected_days)
    turnover_average = (
        sum((Decimal(str(row["value"])) for row in turnover), Decimal("0")) / Decimal(len(turnover))
        if turnover else None
    )
    if fund_kpis:
        portfolio = []
        if aum:
            row = aum[0]
            places = DISPLAY_FORMAT_V1["aum_million_places"]
            portfolio.append({"label": f"Asset Under Management ({row['currency']})^", "value": f"{Decimal(str(row['value'])):,.{places}f} {row['unit']}"})
        if turnover:
            row = turnover[-1]
            # §6: the turnover million value carries no decimals. It used to reuse the AUM
            # format and printed "12,882.00 million" where the reference prints "12,882 million".
            places = DISPLAY_FORMAT_V1["turnover_million_places"]
            rounded = turnover_average.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
            portfolio.append({"label": f"Average Daily Turnover ({row['currency']})^^", "value": f"{rounded:,.{places}f} {row['unit']}"})
        portfolio.append({"label": "Number of holdings", "value": str(positive_weight_count(rows))})
    else:
        # Only what the constituent set alone can support. This used to fall back to
        # `payload["analytics"]["portfolio"]` — copying a pre-formatted answer out of the input and
        # presenting it as a calculated result. `fund_kpi_daily` is a required slot, so a snapshot
        # without it is already incomplete and reports the gap as SNAPSHOT_INCOMPLETE; the missing
        # AUM and turnover rows now simply do not appear.
        portfolio = [
            {"label": "Number of holdings", "value": str(positive_weight_count(rows))}
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
        "turnover_average": str(turnover_average) if turnover_average is not None else None,
        "turnover_coverage": str(Decimal(len(observed_turnover_days)) / Decimal(expected_day_count)) if expected_day_count else None,
        "aum_value": str(aum[0]["value"]) if aum else None,
        "next_rebalancing_date": next_rebalancing_date(payload, as_of_date),
    }
    return analytics, metrics
