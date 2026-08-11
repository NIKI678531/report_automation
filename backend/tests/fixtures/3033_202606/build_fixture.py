"""Build the deterministic 3033 fixture from the supplied CSV/XLSX samples."""
from __future__ import annotations

import csv
import json
from decimal import Decimal
from pathlib import Path

from openpyxl import load_workbook

DOWNLOADS = Path.home() / "Downloads"
CSV_FILE = DOWNLOADS / "HSTECH_eod_con_20260630.csv"
XLSX_FILE = DOWNLOADS / "BBG-hstech constituent monthly update (version 1).xlsx"
OUTPUT = Path(__file__).with_name("snapshot.json")

HSICS_INDUSTRIES = {
    "10": "Industrials",
    "23": "Consumer Discretionary",
    "28": "Healthcare",
    "70": "Information Technology",
}


def code(value: object) -> str:
    return str(int(value)) if isinstance(value, (int, float)) else str(value).split()[0].lstrip("0") or "0"


def total_return_series() -> list[dict[str, str]]:
    history_returns = {
        "FUND": {
            "instrument_code": "3033.HK",
            "2025-12-31": Decimal("-0.1879"),
            "2026-03-31": Decimal("-0.0350"),
            "2026-05-29": Decimal("-0.0822"),
        },
        "BENCHMARK": {
            "instrument_code": "HSTECHN Index",
            "2025-12-31": Decimal("-0.1838"),
            "2026-03-31": Decimal("-0.0324"),
            "2026-05-29": Decimal("-0.0814"),
        },
    }
    rows: list[dict[str, str]] = []
    for role, values in history_returns.items():
        instrument_code = str(values["instrument_code"])
        for trade_date in ("2025-12-31", "2026-03-31", "2026-05-29"):
            period_return = values[trade_date]
            rows.append({
                "instrument_role": role,
                "instrument_code": instrument_code,
                "trade_date": trade_date,
                "total_return_value": str(Decimal("100") / (Decimal("1") + period_return)),
                "series_type": "Total Return",
                "currency": "HKD",
                "source": "GOLDEN_FIXTURE",
            })
        rows.append({
            "instrument_role": role,
            "instrument_code": instrument_code,
            "trade_date": "2026-06-30",
            "total_return_value": "100",
            "series_type": "Total Return",
            "currency": "HKD",
            "source": "GOLDEN_FIXTURE",
        })
    return sorted(rows, key=lambda item: (item["trade_date"], item["instrument_role"]))


def main() -> None:
    with CSV_FILE.open(encoding="utf-8-sig", newline="") as stream:
        csv_rows = {code(row["Lcal Cde"]): row for row in csv.DictReader(stream)}

    workbook = load_workbook(XLSX_FILE, read_only=True, data_only=True)
    returns = {}
    for row in workbook["Formula"].iter_rows(min_row=5, max_col=15, values_only=True):
        if row[12] is not None:
            returns[code(row[12])] = {
                "return_1m": float(row[1]) / 100 if row[1] is not None else None,
                "return_3m": float(row[2]) / 100 if row[2] is not None else None,
                "return_6m": float(row[3]) / 100 if row[3] is not None else None,
                "return_ytd": float(row[4]) / 100 if row[4] is not None else None,
            }
    workbook.close()

    constituents = []
    for security_code, row in csv_rows.items():
        industry_code = str(row["Industry"]).strip().zfill(2)
        industry_name = HSICS_INDUSTRIES[industry_code]
        constituents.append({
            "security_code": security_code,
            "ticker": f"{security_code.zfill(4)}.HK",
            "name_en": row["Stk Name_E"],
            "name_zh_hant": row["Stk Name_TC"],
            "close_price": float(row["Cls Price"]),
            "currency": row["Lcal Ccy"],
            "weight": float(row["Pct Idx Wgt"]) / 100,
            "sector": industry_name,
            "source_codes": {
                "hsics_industry": industry_code,
                "hsics_sector": str(row["Sector"]).strip().zfill(4),
            },
            "source_industry_code": industry_code,
            "effective_industry_code": industry_code,
            "effective_industry_name": industry_name,
            "industry_taxonomy": "HSICS",
            "industry_taxonomy_version": "HSICS-2026-112",
            **returns.get(security_code, {
                "return_1m": None,
                "return_3m": None,
                "return_6m": None,
                "return_ytd": None,
            }),
        })

    constituents.sort(key=lambda item: (-item["weight"], item["security_code"]))
    by_return = sorted(
        (item for item in constituents if item["return_1m"] is not None),
        key=lambda item: (-item["return_1m"], item["security_code"]),
    )
    sector_totals: dict[str, float] = {}
    for item in constituents:
        sector_totals[item["sector"]] = sector_totals.get(item["sector"], 0.0) + item["weight"]

    payload = {
        "as_of_date": "2026-06-30",
        "constituent_index_code": "HSTECH",
        "next_rebalancing_date": "2026-09-04",
        "constituents": constituents,
        "total_return_series": total_return_series(),
        "fund_kpis": [
            {
                "metric_code": "AUM",
                "metric_date": "2026-06-30",
                "value": "67536.55",
                "unit": "million",
                "currency": "HKD",
                "source": "GOLDEN_FIXTURE",
            },
            {
                "metric_code": "DAILY_TURNOVER",
                "metric_date": "2026-06-30",
                "value": "12882",
                "unit": "million",
                "currency": "HKD",
                "source": "GOLDEN_FIXTURE",
            },
        ],
        "trading_calendar": [
            {
                "market": "HK",
                "date": "2026-06-30",
                "is_trading_day": True,
                "source": "GOLDEN_FIXTURE",
            },
        ],
        "index_events": [
            {
                "index_code": "HSTECH",
                "event_type": "REBALANCE",
                "announcement_date": "2026-06-15",
                "effective_date": "2026-09-04",
                "source": "GOLDEN_FIXTURE",
            },
        ],
        "industry_master": {
            "taxonomy": "HSICS",
            "version": "HSICS-2026-112",
            "as_of_date": "2026-06-30",
            "record_count": 4,
            "checksum": "golden-fixture-hsics-2026-112",
        },
        "historical_performance": {
            "rows": [
                {
                    "role": "FUND",
                    "name": "3033.HK",
                    "return_1m": -0.0822,
                    "return_3m": -0.0350,
                    "return_6m": -0.1879,
                    "return_ytd": -0.1879,
                },
                {
                    "role": "BENCHMARK",
                    "name": "HSTECHN Index",
                    "return_1m": -0.0814,
                    "return_3m": -0.0324,
                    "return_6m": -0.1838,
                    "return_ytd": -0.1838,
                },
            ]
        },
        "company_news": [],
        "analytics": {
            "top10": [{"issuer": item["name_en"], "weight": item["weight"]} for item in constituents[:10]],
            "sectors": [{"sector": key, "weight": value} for key, value in sorted(sector_totals.items())],
            "top": [{"issuer": item["name_en"], "return": item["return_1m"]} for item in by_return[:3]],
            "bottom": [{"issuer": item["name_en"], "return": item["return_1m"]} for item in by_return[-3:]],
            "portfolio": [
                {"label": "Asset Under Management (HKD)^", "value": "67,536.55 million"},
                {"label": "Average Daily Turnover (HKD)^^", "value": "12,882 million"},
                {"label": "Number of holdings", "value": str(len(constituents))},
            ],
        },
        "footnotes": {
            "historical": "*Bloomberg, as of 30/06/2026. Return periods follow the approved common-trading-date convention.",
            "constituents": "Source: Bloomberg, Hang Seng Indexes Company Limited, as of 30/06/2026.",
            "analytics": "*Hang Seng Indexes, as of 30/06/2026. ^CSOP, as of 30/06/2026. ^^Bloomberg, 01/06/2026 - 30/06/2026.",
        },
    }
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {OUTPUT} with {len(constituents)} constituents")


if __name__ == "__main__":
    main()
