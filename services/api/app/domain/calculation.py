from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable


def period_return(start: Decimal, end: Decimal) -> Decimal:
    if start <= 0:
        raise ValueError("start total-return value must be greater than zero")
    return end / start - Decimal("1")


def display_percent(value: Decimal | float | int | None, places: int = 2) -> str:
    if value is None:
        return "N/A"
    quant = Decimal(1).scaleb(-places)
    return str((Decimal(str(value)) * Decimal("100")).quantize(quant, rounding=ROUND_HALF_UP))


def stable_rank(rows: Iterable[dict], key: str, descending: bool = True) -> list[dict]:
    return sorted(rows, key=lambda row: ((-Decimal(str(row[key]))) if descending else Decimal(str(row[key])), str(row.get("security_code", ""))))


def sector_breakdown(rows: Iterable[dict]) -> list[dict]:
    totals: dict[str, Decimal] = {}
    for row in rows:
        sector = row.get("sector")
        if not sector:
            raise ValueError(f"missing sector mapping for {row.get('security_code')}")
        totals[sector] = totals.get(sector, Decimal("0")) + Decimal(str(row["weight"]))
    return [{"sector": key, "weight": float(value)} for key, value in sorted(totals.items())]


def quality_checks(payload: dict, expected_constituent_count: int | None = None) -> list[dict]:
    rows = payload.get("constituents", [])
    results: list[dict] = []
    codes = [str(row.get("security_code", "")) for row in rows]
    weight = sum((Decimal(str(row.get("weight", 0))) for row in rows), Decimal("0"))
    checks: list[tuple[str, bool, object, str]] = [
        ("QC-001", len(codes) == len(set(codes)), len(codes), "Security codes must be unique."),
        ("QC-002", abs(weight - Decimal("1")) <= Decimal("0.0001"), float(weight), "Weights must total 100% ± 0.01 percentage points."),
    ]
    if expected_constituent_count is not None:
        checks.append((
            "QC-003",
            len(rows) == expected_constituent_count,
            len(rows),
            f"The selected product profile requires exactly {expected_constituent_count} constituents.",
        ))
    checks.append(("QC-004", all(row.get("sector") for row in rows), sum(1 for row in rows if not row.get("sector")), "Every constituent requires an effective sector mapping."))
    for check_id, passed, actual, hint in checks:
        results.append({
            "check_id": check_id,
            "severity": "BLOCKING",
            "status": "PASSED" if passed else "FAILED",
            "actual": actual,
            "fix_hint": hint,
        })
    return results


FORMULA_VERSION = "total-return-v1"


def calculate_snapshot(payload: dict) -> tuple[dict, dict]:
    rows = payload.get("constituents", [])
    ranked_weight = sorted(rows, key=lambda row: (-Decimal(str(row["weight"])), str(row["security_code"])))
    ranked_return = sorted(
        (row for row in rows if row.get("return_1m") is not None),
        key=lambda row: (-Decimal(str(row["return_1m"])), -Decimal(str(row["weight"])), str(row["security_code"])),
    )
    bottom = sorted(
        (row for row in rows if row.get("return_1m") is not None),
        key=lambda row: (Decimal(str(row["return_1m"])), -Decimal(str(row["weight"])), str(row["security_code"])),
    )
    sectors = sector_breakdown(rows)
    fund_kpis = payload.get("fund_kpis", [])
    if fund_kpis:
        aum_rows = sorted((row for row in fund_kpis if row.get("metric_code") == "AUM"), key=lambda row: row["metric_date"])
        turnover_rows = [row for row in fund_kpis if row.get("metric_code") == "DAILY_TURNOVER"]
        portfolio = []
        if aum_rows:
            row = aum_rows[-1]
            portfolio.append({"label": f"Asset Under Management ({row['currency']})^", "value": f"{Decimal(str(row['value'])):,.2f} {row['unit']}"})
        if turnover_rows:
            average = sum((Decimal(str(row["value"])) for row in turnover_rows), Decimal("0")) / Decimal(len(turnover_rows))
            row = turnover_rows[-1]
            portfolio.append({"label": f"Average Daily Turnover ({row['currency']})^^", "value": f"{average:,.2f} {row['unit']}"})
        portfolio.append({"label": "Number of holdings", "value": str(sum(1 for row in rows if Decimal(str(row["weight"])) > 0))})
    else:
        portfolio = payload.get("analytics", {}).get("portfolio", [
            {"label": "Number of holdings", "value": str(sum(1 for row in rows if Decimal(str(row["weight"])) > 0))}
        ])
    analytics = {
        "top10": [{"issuer": row["name_en"], "weight": row["weight"], "security_code": row["security_code"]} for row in ranked_weight[:10]],
        "sectors": sectors,
        "top": [{"issuer": row["name_en"], "return": row["return_1m"], "security_code": row["security_code"]} for row in ranked_return[:3]],
        "bottom": [{"issuer": row["name_en"], "return": row["return_1m"], "security_code": row["security_code"]} for row in bottom[:3]],
        "portfolio": portfolio,
    }
    metrics = {
        "constituent_count": len(rows),
        "weight_total": float(sum((Decimal(str(row["weight"])) for row in rows), Decimal("0"))),
        "sector_count": len(sectors),
        "top_security_code": ranked_return[0]["security_code"] if ranked_return else None,
        "bottom_security_code": bottom[0]["security_code"] if bottom else None,
        "turnover_observation_count": len([row for row in fund_kpis if row.get("metric_code") == "DAILY_TURNOVER"]),
    }
    return analytics, metrics
