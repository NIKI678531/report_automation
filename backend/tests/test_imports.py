import csv
import io
import json
from datetime import date
from pathlib import Path

import pytest

from app.domain.imports import parse_final_analytics, parse_historical_performance


def fixture_csv() -> bytes:
    snapshot = json.loads((Path(__file__).parent / "fixtures" / "3033_202606" / "snapshot.json").read_text(encoding="utf-8"))
    stream = io.StringIO()
    fields = ["Code", "Constituent Name", "Weighting", "GICS_SECTOR_NAME", "Cls Price", "1-month return (%)", "3-month return (%)", "6-month return (%)", "YTD return (%)"]
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    for row in snapshot["constituents"]:
        writer.writerow({
            "Code": row["security_code"], "Constituent Name": row["name_en"], "Weighting": row["weight"],
            "GICS_SECTOR_NAME": row["sector"], "Cls Price": row["close_price"],
            "1-month return (%)": row["return_1m"] * 100, "3-month return (%)": row["return_3m"] * 100,
            "6-month return (%)": row["return_6m"] * 100, "YTD return (%)": row["return_ytd"] * 100,
        })
    return stream.getvalue().encode("utf-8")


def test_upload_diff_and_apply(client):
    report = client.post("/api/v1/reports", json={"report_date": "2026-06-30"}).json()
    golden = client.post(f"/api/v1/reports/{report['id']}/snapshots", json={"source_policy": "GOLDEN_FIXTURE"})
    assert golden.status_code == 201
    upload = client.post(
        f"/api/v1/reports/{report['id']}/imports",
        data={"dataset_type": "constituents"},
        files={"file": ("constituents.csv", fixture_csv(), "text/csv")},
    )
    assert upload.status_code == 201, upload.text
    body = upload.json()
    assert body["status"] == "VALIDATED"
    assert len(body["payload"]["constituents"]) == 30
    assert body["diff"]["summary"] == {"added": 0, "removed": 0, "changed": 0}
    applied = client.post(f"/api/v1/reports/{report['id']}/imports/{body['id']}/apply", json={"reason": "Approved UAT data override"})
    assert applied.status_code == 200, applied.text
    assert applied.json()["source_policy"] == "UPLOAD_OVERRIDE"


def test_upload_rejects_unsupported_file(client):
    report = client.post("/api/v1/reports", json={"report_date": "2026-06-30"}).json()
    response = client.post(f"/api/v1/reports/{report['id']}/imports", files={"file": ("bad.txt", b"bad", "text/plain")})
    # A file the parser cannot read is recorded as a REJECTED import rather than discarded, so the
    # user can see why. The error envelope is flat: {error_code, message, severity, fix_hint}.
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "REJECTED"
    assert [item["error_code"] for item in body["validation_results"]] == ["IMPORT_PARSE_FAILED"]
    assert body["summary"]["blocking"] == 1


def test_historical_performance_csv_calculates_common_period_returns():
    data = (
        "instrument_role,instrument_code,trade_date,total_return_value,series_type,currency,source\n"
        "FUND,3033.HK,2025-12-30,100,Total Return,HKD,Approved\n"
        "BENCHMARK,HSTECH,2025-12-30,200,Total Return,HKD,Approved\n"
        "FUND,3033.HK,2025-12-31,100,Total Return,HKD,Approved\n"
        "BENCHMARK,HSTECH,2025-12-31,200,Total Return,HKD,Approved\n"
        "FUND,3033.HK,2026-03-30,110,Total Return,HKD,Approved\n"
        "BENCHMARK,HSTECH,2026-03-30,220,Total Return,HKD,Approved\n"
        "FUND,3033.HK,2026-03-31,110,Total Return,HKD,Approved\n"
        "BENCHMARK,HSTECH,2026-03-31,220,Total Return,HKD,Approved\n"
        "FUND,3033.HK,2026-05-29,120,Total Return,HKD,Approved\n"
        "BENCHMARK,HSTECH,2026-05-29,240,Total Return,HKD,Approved\n"
        "FUND,3033.HK,2026-06-30,125,Total Return,HKD,Approved\n"
        "BENCHMARK,HSTECH,2026-06-30,250,Total Return,HKD,Approved\n"
    ).encode()
    parsed = parse_historical_performance("history.csv", data, date(2026, 6, 30))
    assert parsed["historical_performance"]["effective_as_of"] == "2026-06-30"
    assert float(parsed["historical_performance"]["rows"][0]["return_1m"]) == pytest.approx(0.0416666667)
    assert float(parsed["historical_performance"]["rows"][0]["return_ytd"]) == pytest.approx(0.25)
    assert parsed["historical_performance"]["periods"]["return_3m"]["period_start"] == "2026-03-30"


def test_final_analytics_csv_normalizes_constituents_and_kpis():
    data = (
        "record_type,as_of_date,security_code,ticker,name_en,name_zh_hant,close_price,currency,value_scale,weight,sector,return_1m,return_3m,return_6m,return_ytd,metric_code,metric_date,value,unit,source,market,calendar_date,is_trading_day,index_code,event_type,announcement_date,effective_date\n"
        "CONSTITUENT,2026-06-30,1,0001.HK,Alpha,,10,HKD,PERCENT,60,Technology,10,11,12,13,,,,,,,,,,,,,,,\n"
        "CONSTITUENT,2026-06-30,2,0002.HK,Beta,,20,HKD,PERCENT,40,Financials,-5,-4,-3,-2,,,,,,,,,,,,,,,\n"
        "KPI,,,,,,,HKD,,,,,,,,AUM,2026-06-30,1000,million,Approved,,,,,,,\n"
        "KPI,,,,,,,HKD,,,,,,,,DAILY_TURNOVER,2026-06-29,50,million,Approved,,,,,,,\n"
        "CALENDAR,,,,,,,,,,,,,,,,,,,Approved,HK,2026-06-29,true,,,,\n"
        "EVENT,,,,,,,,,,,,,,,,,,,Approved,,,,HSTECH,REBALANCE,2026-08-21,2026-09-04\n"
    ).encode()
    parsed = parse_final_analytics("analytics.csv", data, date(2026, 6, 30))
    assert [row["security_code"] for row in parsed["constituents"]] == ["1", "2"]
    assert float(parsed["constituents"][0]["weight"]) == pytest.approx(0.6)
    assert float(parsed["constituents"][0]["return_1m"]) == pytest.approx(0.1)
    assert {row["metric_code"] for row in parsed["fund_kpis"]} == {"AUM", "DAILY_TURNOVER"}
    assert parsed["trading_calendar"] == [{"market": "HK", "date": "2026-06-29", "is_trading_day": True, "source": "Approved"}]
    assert parsed["index_events"][0]["effective_date"] == "2026-09-04"


@pytest.mark.parametrize(
    ("row", "message"),
    [
        ("CONSTITUENT,2026-05-31,1,0001.HK,Alpha,,10,HKD,PERCENT,100,Technology,10,11,12,13,,,,,,", "as_of_date must be in the report month"),
        ("KPI,,,,,,,HKD,,,,,,,,AUM,2026-05-31,1000,million,Approved", "metric_date must be in the report month"),
    ],
)
def test_final_analytics_rejects_dates_outside_report_month(row, message):
    header = "record_type,as_of_date,security_code,ticker,name_en,name_zh_hant,close_price,currency,value_scale,weight,sector,return_1m,return_3m,return_6m,return_ytd,metric_code,metric_date,value,unit,source\n"
    with pytest.raises(ValueError, match=message):
        parse_final_analytics("analytics.csv", f"{header}{row}\n".encode(), date(2026, 6, 30))


def historical_csv() -> bytes:
    rows = [
        ("2025-12-30", 100, 200), ("2025-12-31", 100, 200),
        ("2026-03-30", 110, 220), ("2026-05-29", 120, 240), ("2026-06-30", 125, 250),
    ]
    output = "instrument_role,instrument_code,trade_date,total_return_value,series_type,currency,source\n"
    for trade_date, fund, benchmark in rows:
        output += f"FUND,3033.HK,{trade_date},{fund},Total Return,HKD,Approved\n"
        output += f"BENCHMARK,HSTECH,{trade_date},{benchmark},Total Return,HKD,Approved\n"
    return output.encode()


def final_analytics_csv() -> bytes:
    return (
        "record_type,as_of_date,security_code,ticker,name_en,name_zh_hant,close_price,currency,value_scale,weight,sector,return_1m,return_3m,return_6m,return_ytd,metric_code,metric_date,value,unit,source,market,calendar_date,is_trading_day,index_code,event_type,announcement_date,effective_date\n"
        "CONSTITUENT,2026-06-30,1,0001.HK,Alpha,,10,HKD,PERCENT,60,Technology,10,11,12,13,,,,,,,,,,,,,,,\n"
        "CONSTITUENT,2026-06-30,2,0002.HK,Beta,,20,HKD,PERCENT,40,Financials,-5,-4,-3,-2,,,,,,,,,,,,,,,\n"
        "KPI,,,,,,,HKD,,,,,,,,AUM,2026-06-30,1000,million,Approved,,,,,,,\n"
        "KPI,,,,,,,HKD,,,,,,,,DAILY_TURNOVER,2026-06-29,50,million,Approved,,,,,,,\n"
        "CALENDAR,,,,,,,,,,,,,,,,,,,Approved,HK,2026-06-29,true,,,,\n"
        "EVENT,,,,,,,,,,,,,,,,,,,Approved,,,,TESTIDX,REBALANCE,2026-08-21,2026-09-04\n"
    ).encode()


def test_historical_import_creates_new_snapshot_without_mutating_base(client):
    report = client.post("/api/v1/reports", json={"report_date": "2026-06-30"}).json()
    base = client.post(f"/api/v1/reports/{report['id']}/snapshots", json={"source_policy": "GOLDEN_FIXTURE"}).json()
    uploaded = client.post(
        f"/api/v1/reports/{report['id']}/imports",
        data={"dataset_type": "historical_performance"},
        files={"file": ("history.csv", historical_csv(), "text/csv")},
    )
    assert uploaded.status_code == 201, uploaded.text
    applied = client.post(f"/api/v1/reports/{report['id']}/imports/{uploaded.json()['id']}/apply", json={"reason": "Approved total return update"})
    assert applied.status_code == 200, applied.text
    assert applied.json()["id"] != base["id"]
    assert float(applied.json()["payload"]["historical_performance"]["rows"][0]["return_ytd"]) == pytest.approx(0.25)
    unchanged = client.get(f"/api/v1/reports/{report['id']}/snapshots/{base['id']}").json()
    assert unchanged["checksum"] == base["checksum"]
    assert unchanged["payload"] == base["payload"]


def test_final_analytics_import_calculates_portfolio_without_mutating_snapshot(client):
    report = client.post("/api/v1/reports", json={"product_code": "TEST", "report_date": "2026-06-30"}).json()
    uploaded = client.post(
        f"/api/v1/reports/{report['id']}/imports",
        data={"dataset_type": "final_analytics"},
        files={"file": ("analytics.csv", final_analytics_csv(), "text/csv")},
    )
    assert uploaded.status_code == 201, uploaded.text
    applied = client.post(f"/api/v1/reports/{report['id']}/imports/{uploaded.json()['id']}/apply", json={"reason": "Approved analytics inputs"})
    assert applied.status_code == 200, applied.text
    input_checksum = applied.json()["checksum"]
    calculated = client.post(f"/api/v1/reports/{report['id']}/calculations")
    assert calculated.status_code == 200, calculated.text
    detail = client.get(f"/api/v1/reports/{report['id']}").json()
    portfolio = detail["latest_document"]["content"]["sections"]["analytics"]["portfolio"]
    assert [row["label"] for row in portfolio] == ["Asset Under Management (HKD)^", "Average Daily Turnover (HKD)^^", "Number of holdings"]
    preview = client.post(f"/api/v1/reports/{report['id']}/preview")
    assert preview.status_code == 200, preview.text
    assert "conic-gradient(#5186bd 0.0000% 40.0000%,#223a8b 40.0000% 100.0000%)" in preview.text
    assert "Financials" in preview.text
    assert "Technology" in preview.text
    assert "Next Rebalancing Date: 2026-09-04" in preview.text
    unchanged = client.get(f"/api/v1/reports/{report['id']}/snapshots/{applied.json()['id']}").json()
    assert unchanged["checksum"] == input_checksum
    assert "analytics" in unchanged["payload"] and unchanged["payload"]["analytics"]["top10"] == []
