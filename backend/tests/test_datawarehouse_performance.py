import sqlite3
from datetime import date
from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.integrations.datawarehouse import DataWarehouseProviderError, load_historical_performance
from app.domain import snapshot_composer


def build_performance_snapshot(path, *, include_returns: bool = True) -> None:
    connection = sqlite3.connect(path)
    connection.executescript("""
        CREATE TABLE view_ads_busi_product_fundinfo_class_f_p (
            class_id TEXT, tradar_code TEXT, fund_name_en TEXT, class_name TEXT,
            class_type TEXT, ticker TEXT, index_ticker TEXT
        );
        CREATE TABLE view_ads_busi_performance_class_returns_f_p (
            trade_date TEXT, tradar_code TEXT, class_id TEXT, class_name TEXT,
            returns_l1m NUMERIC, returns_l3m NUMERIC, returns_l6m NUMERIC, returns_ytd NUMERIC
        );
        CREATE TABLE view_ads_busi_performance_index_returns_f_p (
            trade_date TEXT, class_id TEXT, index_ticker TEXT,
            returns_l1m NUMERIC, returns_l3m NUMERIC, returns_l6m NUMERIC, returns_ytd NUMERIC
        );
        INSERT INTO view_ads_busi_product_fundinfo_class_f_p VALUES
            ('CLS00178', 'CO-CHST', 'CSOP Hang Seng TECH Index ETF', 'HKD Share Class A',
             'LISTED', '3033 HK EQUITY', 'HSTECHN Index'),
            ('CLS00199', 'CO-CHST', 'CSOP Hang Seng TECH Index ETF', 'HKD Share Class unlisted A',
             'UNLISTED', '3033UA HK EQUITY', 'HSTECHN Index');
    """)
    if include_returns:
        connection.executescript("""
            INSERT INTO view_ads_busi_performance_class_returns_f_p VALUES
                ('2025-01-30', 'CO-CHST', 'CLS00178', 'HKD Share Class A', 0.01, 0.03, 0.06, 0.01),
                ('2025-01-31', 'CO-CHST', 'CLS00178', 'HKD Share Class A', 0.02, 0.04, 0.07, 0.02),
                ('2025-02-28', 'CO-CHST', 'CLS00178', 'HKD Share Class A', 0.05, 0.08, 0.10, 0.071),
                ('2025-03-28', 'CO-CHST', 'CLS00178', 'HKD Share Class A', -0.01, 0.02, 0.05, 0.06029);
            INSERT INTO view_ads_busi_performance_index_returns_f_p VALUES
                ('2025-01-30', 'CLS00178', 'HSTECHN Index', 0.011, 0.031, 0.061, 0.011),
                ('2025-01-31', 'CLS00178', 'HSTECHN Index', 0.021, 0.041, 0.071, 0.021),
                ('2025-02-28', 'CLS00178', 'HSTECHN Index', 0.051, 0.081, 0.101, 0.073071),
                ('2025-03-28', 'CLS00178', 'HSTECHN Index', -0.009, 0.021, 0.051, 0.063413);
        """)
    connection.commit()
    connection.close()


def test_loads_latest_common_row_for_each_selected_month(tmp_path, monkeypatch):
    database = tmp_path / "warehouse.db"
    build_performance_snapshot(database)
    monkeypatch.setattr(settings, "datawarehouse_sqlite_path", database)
    monkeypatch.setattr(settings, "datawarehouse_sqlite_sha256", None)

    result = load_historical_performance(
        fund_ticker="3033.HK",
        benchmark_instrument_code="HSTECHN",
        report_date=date(2025, 3, 31),
        formula_version="warehouse-period-return-v1",
        month_count=3,
    )

    history = result["historical_performance"]
    assert history["requested_report_month"] == "2025-03"
    assert history["effective_as_of"] == "2025-03-28"
    assert [item["month"] for item in history["monthly_observations"]] == [
        "2025-03", "2025-02", "2025-01",
    ]
    assert history["rows"][0]["return_1m"] == "-0.01"
    assert history["rows"][1]["return_ytd"] == "0.063413"
    assert history["source_mapping"]["tradar_code"] == "CO-CHST"
    assert history["source_mapping"]["class_id"] == "CLS00178"
    assert result["datasets"]["historical_performance"]["source_type"] == "DATAWAREHOUSE_SQLITE"


def test_reports_3033_master_mapping_but_missing_return_rows(tmp_path, monkeypatch):
    database = tmp_path / "warehouse-without-returns.db"
    build_performance_snapshot(database, include_returns=False)
    monkeypatch.setattr(settings, "datawarehouse_sqlite_path", database)
    monkeypatch.setattr(settings, "datawarehouse_sqlite_sha256", None)

    with pytest.raises(DataWarehouseProviderError) as raised:
        load_historical_performance(
            fund_ticker="3033.HK",
            benchmark_instrument_code="HSTECHN",
            report_date=date(2025, 12, 31),
            formula_version="warehouse-period-return-v1",
        )

    assert raised.value.code == "DATAWAREHOUSE_PERFORMANCE_NOT_FOUND"
    assert "CO-CHST / CLS00178" in raised.value.message


def test_composer_prefers_warehouse_period_returns_over_legacy_series(tmp_path, monkeypatch):
    database = tmp_path / "warehouse.db"
    build_performance_snapshot(database)
    monkeypatch.setattr(settings, "datawarehouse_sqlite_path", database)
    monkeypatch.setattr(settings, "datawarehouse_sqlite_sha256", None)
    monkeypatch.setattr(settings, "datawarehouse_performance_enabled", True)
    monkeypatch.setattr(snapshot_composer, "load_monthly_data", lambda **kwargs: {
        "total_return_series": [{"instrument_code": "legacy"}],
        "fund_kpis": [],
        "trading_calendar": [],
        "index_events": [],
        "datasets": {"total_return_series": {"source_type": "DA_REPORT_SQLITE"}},
        "_findings": [],
    })
    product = SimpleNamespace(
        ticker="3033.HK",
        benchmark_instrument_code="HSTECHN",
        formula_profile="warehouse-period-return-v1",
        fund_total_return_instrument_code="3033.HK",
        fund_kpi_product_code="3033",
        trading_calendar_code="HK",
        constituent_index_code="HSTECH",
    )

    fragment, findings = snapshot_composer.compose_da_report_fragment(product, date(2025, 3, 31))

    assert not findings
    assert "total_return_series" not in fragment
    assert "total_return_series" not in fragment["datasets"]
    assert fragment["historical_performance"]["effective_as_of"] == "2025-03-28"
    assert fragment["datasets"]["historical_performance"]["source_type"] == "DATAWAREHOUSE_SQLITE"
