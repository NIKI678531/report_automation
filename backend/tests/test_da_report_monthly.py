import sqlite3
from datetime import date

import pytest

from app.core.config import settings
from app.integrations.da_report import DaReportProviderError, load_monthly_data


def build_monthly_snapshot(path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript("""
        CREATE TABLE total_return_series (
            id INTEGER PRIMARY KEY, instrument_code TEXT, trade_date TEXT,
            total_return_value REAL, series_type TEXT, currency TEXT, source TEXT, updated_at TEXT
        );
        CREATE TABLE fund_kpi_daily (
            id INTEGER PRIMARY KEY, product_code TEXT, metric_date TEXT, metric_code TEXT,
            value REAL, unit TEXT, currency TEXT, source TEXT, updated_at TEXT
        );
        CREATE TABLE trading_calendar (
            id INTEGER PRIMARY KEY, market_code TEXT, trade_date TEXT, is_trading_day INTEGER,
            source TEXT, updated_at TEXT
        );
        CREATE TABLE index_events (
            id INTEGER PRIMARY KEY, index_code TEXT, event_type TEXT, announcement_date TEXT,
            effective_date TEXT, source TEXT, updated_at TEXT
        );
        INSERT INTO total_return_series VALUES
            (1, '3033.HK', '2025-12-31', 100, 'TOTAL_RETURN', 'HKD', 'Official', '2026-07-01'),
            (2, 'HSTECHN', '2025-12-31', 200, 'TOTAL_RETURN', 'HKD', 'Official', '2026-07-01'),
            (3, '3033.HK', '2026-05-29', 110, 'TOTAL_RETURN', 'HKD', 'Official', '2026-07-01'),
            (4, 'HSTECHN', '2026-05-29', 220, 'TOTAL_RETURN', 'HKD', 'Official', '2026-07-01'),
            (5, '3033.HK', '2026-06-30', 120, 'TOTAL_RETURN', 'HKD', 'Official', '2026-07-01'),
            (6, 'HSTECHN', '2026-06-30', 240, 'TOTAL_RETURN', 'HKD', 'Official', '2026-07-01');
        INSERT INTO fund_kpi_daily VALUES
            (1, '3033', '2026-06-30', 'AUM', 1000, 'million', 'HKD', 'Official', '2026-07-01'),
            (2, '3033', '2026-06-29', 'DAILY_TURNOVER', 50, 'million', 'HKD', 'Official', '2026-07-01'),
            (3, '3033', '2026-06-30', 'DAILY_TURNOVER', 70, 'million', 'HKD', 'Official', '2026-07-01');
        INSERT INTO trading_calendar VALUES
            (1, 'HK', '2026-06-29', 1, 'Official', '2026-07-01'),
            (2, 'HK', '2026-06-30', 1, 'Official', '2026-07-01');
        INSERT INTO index_events VALUES
            (1, 'HSTECH', 'REBALANCE', '2026-06-15', '2026-09-04', 'Official', '2026-07-01');
    """)
    connection.commit()
    connection.close()


def test_monthly_data_uses_product_bindings_and_preserves_lineage(tmp_path, monkeypatch):
    database = tmp_path / "da-report.sqlite"
    build_monthly_snapshot(database)
    monkeypatch.setattr(settings, "da_report_sqlite_path", database)
    monkeypatch.setattr(settings, "da_report_sqlite_sha256", None)

    payload = load_monthly_data(
        product_code="3033",
        fund_instrument_code="3033.HK",
        benchmark_instrument_code="HSTECHN",
        trading_calendar_code="HK",
        constituent_index_code="HSTECH",
        report_date=date(2026, 6, 30),
    )

    assert {row["instrument_role"] for row in payload["total_return_series"]} == {"FUND", "BENCHMARK"}
    assert len(payload["fund_kpis"]) == 3
    assert payload["index_events"][0]["effective_date"] == "2026-09-04"
    lineage = payload["datasets"]["total_return_series"]["lineage"]
    assert lineage["source_table"] == "total_return_series"
    assert lineage["source_record_ids"] == [1, 2, 3, 4, 5, 6]
    assert len(lineage["sqlite_checksum"]) == 64


def test_monthly_schema_failure_does_not_require_news_tables(tmp_path, monkeypatch):
    database = tmp_path / "incomplete.sqlite"
    sqlite3.connect(database).close()
    monkeypatch.setattr(settings, "da_report_sqlite_path", database)
    monkeypatch.setattr(settings, "da_report_sqlite_sha256", None)

    with pytest.raises(DaReportProviderError) as raised:
        load_monthly_data(
            product_code="3033",
            fund_instrument_code="3033.HK",
            benchmark_instrument_code="HSTECHN",
            trading_calendar_code="HK",
            constituent_index_code="HSTECH",
            report_date=date(2026, 6, 30),
        )

    assert raised.value.code == "DA_REPORT_MONTHLY_SCHEMA_MISMATCH"


def test_report_auto_snapshot_becomes_valid_after_one_constituent_upload(client, tmp_path, monkeypatch):
    database = tmp_path / "da-report-auto.sqlite"
    build_monthly_snapshot(database)
    monkeypatch.setattr(settings, "da_report_sqlite_path", database)
    monkeypatch.setattr(settings, "da_report_sqlite_sha256", None)
    monkeypatch.setattr(settings, "da_report_auto_load", True)
    master = (
        "taxonomy,version,level,code,parent_code,name_en,name_zh_hant,valid_from,valid_to,source,source_record_key\n"
        "HSICS,HSICS-2026-112,INDUSTRY,23,,Consumer Discretionary,,2026-01-01,2026-12-31,Official,industry-23\n"
        "HSICS,HSICS-2026-112,INDUSTRY,70,,Information Technology,,2026-01-01,2026-12-31,Official,industry-70\n"
    ).encode()
    imported_master = client.post(
        "/api/v1/industry-master/import",
        files={"file": ("hsics.csv", master, "text/csv")},
        headers={"X-User-Role": "ADMIN"},
    )
    assert imported_master.status_code == 201, imported_master.text

    report = client.post("/api/v1/reports", json={"product_code": "3033", "report_date": "2026-06-30"})

    assert report.status_code == 201, report.text
    detail = client.get(f"/api/v1/reports/{report.json()['id']}").json()
    auto_snapshot = client.get(
        f"/api/v1/reports/{detail['id']}/snapshots/{detail['active_snapshot_id']}"
    ).json()
    assert auto_snapshot["status"] == "PENDING"
    assert auto_snapshot["source_policy"] == "DA_REPORT_AUTO"
    assert auto_snapshot["payload"]["historical_performance"]["rows"]
    assert auto_snapshot["payload"]["datasets"]["fund_kpi_daily"]["source_type"] == "DA_REPORT_SQLITE"

    constituents = (
        "index_code,as_of_date,security_code,ticker,name_en,name_zh_hant,close_price,currency,weight_pct,source_industry_code,period_end,period_start_1m,return_1m_pct,return_1m_missing_reason,period_start_3m,return_3m_pct,return_3m_missing_reason,period_start_6m,return_6m_pct,return_6m_missing_reason,period_start_ytd,return_ytd_pct,return_ytd_missing_reason,constituent_source,return_source\n"
        "HSTECH,2026-06-30,1,0001.HK,Alpha,,10,HKD,50,70,2026-06-30,2026-05-29,10,,2026-03-31,11,,2025-12-31,12,,2025-12-31,13,,Official Index,Official Returns\n"
        "HSTECH,2026-06-30,2,0002.HK,Beta,,20,HKD,50,23,2026-06-30,2026-05-29,-5,,2026-03-31,-4,,2025-12-31,-3,,2025-12-31,-2,,Official Index,Official Returns\n"
    ).encode()
    uploaded = client.post(
        f"/api/v1/reports/{detail['id']}/imports",
        data={"dataset_type": "constituent_performance"},
        files={"file": ("constituent-performance.csv", constituents, "text/csv")},
    ).json()
    applied = client.post(f"/api/v1/reports/{detail['id']}/imports/{uploaded['id']}/apply", json={})

    assert applied.status_code == 200, applied.text
    assert applied.json()["status"] == "VALID"
    assert applied.json()["source_policy"] == "DA_REPORT_PLUS_UPLOAD"
    calculated = client.get(f"/api/v1/reports/{detail['id']}").json()
    assert calculated["status"] == "EDITING"
    assert calculated["latest_document"]["content"]["sections"]["analytics"]["top10"]
    modules = {
        item["module_code"]: set(item["source_dataset_types"])
        for item in client.get(f"/api/v1/reports/{detail['id']}/modules").json()
    }
    assert modules["historical_performance"] == {"total_return_series"}
    assert modules["constituents_performance"] == {
        "constituent_snapshot", "constituent_period_return", "index_event",
    }
    assert modules["final_analytics"] == {
        "constituent_snapshot", "constituent_period_return", "industry_master",
        "fund_kpi_daily", "trading_calendar",
    }
    metrics = client.get(f"/api/v1/reports/{detail['id']}/metrics").json()
    constituent_3m = next(
        item for item in metrics
        if item["metric_code"] == "constituent.return_3m" and item["dimension_key"] == "1"
    )
    historical_3m = next(
        item for item in metrics
        if item["metric_code"] == "historical.return_3m" and item["dimension_key"] == "FUND"
    )
    assert constituent_3m["period_start"] == "2026-03-31"
    assert historical_3m["period_start"] == "2025-12-31"
    upload_checksum = applied.json()["payload"]["datasets"]["constituent_performance"]["checksum"]

    refreshed = client.post(
        f"/api/v1/reports/{detail['id']}/snapshots",
        json={"source_policy": "DA_REPORT_AUTO", "mapping_version": "da-report-monthly-v1"},
    )

    assert refreshed.status_code == 201, refreshed.text
    assert refreshed.json()["id"] != applied.json()["id"]
    assert refreshed.json()["status"] == "VALID"
    assert refreshed.json()["payload"]["datasets"]["constituent_performance"]["checksum"] == upload_checksum