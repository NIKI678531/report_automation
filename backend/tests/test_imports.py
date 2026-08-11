from datetime import date

import pytest

from app.domain.imports import (
    parse_fund_kpi_daily,
    parse_index_events,
    parse_total_return_series,
    parse_trading_calendar,
)


def historical_csv() -> bytes:
    rows = [
        ("2025-12-31", 100, 200),
        ("2026-03-31", 110, 220),
        ("2026-05-29", 120, 240),
        ("2026-06-30", 125, 250),
    ]
    output = "instrument_role,instrument_code,trade_date,total_return_value,series_type,currency,source\n"
    for trade_date, fund, benchmark in rows:
        output += f"FUND,3033.HK,{trade_date},{fund},Total Return,HKD,Official\n"
        output += f"BENCHMARK,HSTECHN,{trade_date},{benchmark},Total Return,HKD,Official\n"
    return output.encode()


def test_unknown_file_is_retained_as_needs_mapping(client):
    report = client.post("/api/v1/reports", json={"report_date": "2026-06-30"}).json()
    response = client.post(
        f"/api/v1/reports/{report['id']}/imports",
        data={"dataset_type": "index_constituents"},
        files={"file": ("bad.txt", b"bad", "text/plain")},
    )

    assert response.status_code == 201, response.text
    assert response.json()["status"] == "NEEDS_MAPPING"
    assert response.json()["summary"]["blocking"] == 1


def test_total_return_series_slot_keeps_only_raw_observations():
    parsed = parse_total_return_series("total-returns.csv", historical_csv(), date(2026, 6, 30))

    assert set(parsed) == {"total_return_series"}
    assert len(parsed["total_return_series"]) == 8
    assert {row["instrument_role"] for row in parsed["total_return_series"]} == {"FUND", "BENCHMARK"}


def test_daily_kpi_calendar_and_event_slots_parse_independently():
    kpis = parse_fund_kpi_daily(
        "fund-kpis.csv",
        (
            "metric_code,metric_date,value,unit,currency,source\n"
            "AUM,2026-06-30,1000,million,HKD,Official\n"
            "DAILY_TURNOVER,2026-06-29,50,million,HKD,Official\n"
        ).encode(),
        date(2026, 6, 30),
    )
    calendar = parse_trading_calendar(
        "calendar.csv",
        "market,date,is_trading_day,source\nHK,2026-06-29,true,Official\n".encode(),
        date(2026, 6, 30),
    )
    events = parse_index_events(
        "events.csv",
        "index_code,event_type,announcement_date,effective_date,source\nHSTECH,REBALANCE,2026-06-15,2026-09-04,Official\n".encode(),
        date(2026, 6, 30),
    )

    assert {row["metric_code"] for row in kpis["fund_kpis"]} == {"AUM", "DAILY_TURNOVER"}
    assert calendar["trading_calendar"] == [{"market": "HK", "date": "2026-06-29", "is_trading_day": True, "source": "Official"}]
    assert events["index_events"][0]["effective_date"] == "2026-09-04"


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (
            b"metric_code,metric_date,value,unit,currency,source\nAUM,2026-05-31,1000,million,HKD,Official\nDAILY_TURNOVER,2026-06-29,50,million,HKD,Official\n",
            "metric_date must be in the report month",
        ),
        (
            b"metric_code,metric_date,value,unit,currency,source\nAUM,2026-06-30,1000,million,HKD,Official\n",
            "requires at least one DAILY_TURNOVER",
        ),
    ],
)
def test_fund_kpi_slot_rejects_incomplete_or_out_of_month_data(data, message):
    with pytest.raises(ValueError, match=message):
        parse_fund_kpi_daily("fund-kpis.csv", data, date(2026, 6, 30))
