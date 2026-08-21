import sqlite3
from datetime import date
from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.integrations import datawarehouse
from app.integrations.datawarehouse import (
    DataWarehouseProviderError,
    load_historical_performance,
    load_index_constituents,
)
from app.domain import snapshot_composer


@pytest.fixture(autouse=True)
def isolate_live_cdb_configuration(monkeypatch):
    """Unit fixtures must never inherit credentials from the developer's local .env."""
    monkeypatch.setattr(settings, "datawarehouse_mysql_host", None)
    monkeypatch.setattr(settings, "datawarehouse_mysql_database", None)
    monkeypatch.setattr(settings, "datawarehouse_mysql_username", None)
    monkeypatch.setattr(settings, "datawarehouse_mysql_password", None)
    monkeypatch.setattr(settings, "datawarehouse_mysql_ssl_ca", None)


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
            trade_date TEXT, tradar_code TEXT, class_id TEXT, index_ticker TEXT,
            returns_l1m NUMERIC, returns_l3m NUMERIC, returns_l6m NUMERIC, returns_ytd NUMERIC
        );
        CREATE TABLE view_ads_busi_market_index_constituent_price_daily_f_p (
            trade_date TEXT, index_code TEXT, stock_code TEXT, stock_name TEXT,
            stock_name_eng TEXT, ccy TEXT, index_weight NUMERIC, close_price NUMERIC,
            industry_code TEXT, industry_code2 TEXT, industry_code3 TEXT, sector TEXT
        );
        INSERT INTO view_ads_busi_product_fundinfo_class_f_p VALUES
            ('CLS00178', 'CO-CHST', 'CSOP Hang Seng TECH Index ETF', 'HKD Share Class A',
             'LISTED', '3033 HK EQUITY', 'HSTECHN Index'),
            ('CLS00199', 'CO-CHST', 'CSOP Hang Seng TECH Index ETF', 'HKD Share Class unlisted A',
             'UNLISTED', '3033UA HK EQUITY', 'HSTECHN Index');
        INSERT INTO view_ads_busi_market_index_constituent_price_daily_f_p VALUES
            ('2025-03-28', 'HSTECH', '700 HK EQUITY', '騰訊控股', 'TENCENT', 'HKD', 0.6, 500, '', '', '', '7020'),
            ('2025-03-28', 'HSTECH', '1810 HK EQUITY', '小米集團', 'XIAOMI - W', 'HKD', 0.4, 40, '', '', '', '7010');
    """)
    if include_returns:
        connection.executescript("""
            INSERT INTO view_ads_busi_performance_class_returns_f_p VALUES
                ('2025-01-30', 'CO-CHST', 'CLS00178', 'HKD Share Class A', 0.01, 0.03, 0.06, 0.01),
                ('2025-01-31', 'CO-CHST', 'CLS00178', 'HKD Share Class A', 0.02, 0.04, 0.07, 0.02),
                ('2025-02-28', 'CO-CHST', 'CLS00178', 'HKD Share Class A', 0.05, 0.08, 0.10, 0.071),
                ('2025-03-28', 'CO-CHST', 'CLS00178', 'HKD Share Class A', -0.01, 0.02, 0.05, 0.06029);
            INSERT INTO view_ads_busi_performance_index_returns_f_p VALUES
                ('2025-01-30', 'CO-CHST', 'CLS00178', 'HSTECHN Index', 0.011, 0.031, 0.061, 0.011),
                ('2025-01-31', 'CO-CHST', 'CLS00178', 'HSTECHN Index', 0.021, 0.041, 0.071, 0.021),
                ('2025-02-28', 'CO-CHST', 'CLS00178', 'HSTECHN Index', 0.051, 0.081, 0.101, 0.073071),
                ('2025-03-28', 'CO-CHST', 'CLS00178', 'HSTECHN Index', -0.009, 0.021, 0.051, 0.063413);
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


def test_prefers_read_only_cdb_mysql_when_configured(tmp_path, monkeypatch):
    database = tmp_path / "warehouse.db"
    build_performance_snapshot(database)
    monkeypatch.setattr(settings, "datawarehouse_mysql_host", "warehouse.internal")
    monkeypatch.setattr(settings, "datawarehouse_mysql_port", 3306)
    monkeypatch.setattr(settings, "datawarehouse_mysql_database", "csop_db_dw_ads")
    monkeypatch.setattr(settings, "datawarehouse_mysql_username", "readonly")
    monkeypatch.setattr(settings, "datawarehouse_mysql_password", "secret")
    monkeypatch.setattr(settings, "datawarehouse_mysql_ssl_ca", None)
    monkeypatch.setattr(
        datawarehouse,
        "_mysql_engine",
        lambda *args: datawarehouse._sqlite_engine(str(database.resolve())),
    )

    result = load_historical_performance(
        fund_ticker="3033.HK",
        benchmark_instrument_code="HSTECHN",
        report_date=date(2025, 3, 31),
        formula_version="warehouse-period-return-v1",
    )

    dataset = result["datasets"]["historical_performance"]
    assert dataset["source_type"] == "CDB_MYSQL"
    assert dataset["source_object"].startswith("csop_db_dw_ads#")
    assert dataset["lineage"]["source_system"] == "CSOP_CDB_MYSQL"
    assert dataset["lineage"]["source_record_keys"][0] == "CO-CHST:CLS00178:2025-03-28"


def test_loads_cdb_index_constituents_for_the_performance_effective_date(tmp_path, monkeypatch):
    database = tmp_path / "warehouse.db"
    build_performance_snapshot(database)
    monkeypatch.setattr(settings, "datawarehouse_sqlite_path", database)
    monkeypatch.setattr(settings, "datawarehouse_sqlite_sha256", None)

    result = load_index_constituents(
        index_code="HSTECH",
        report_date=date(2025, 3, 31),
        effective_as_of=date(2025, 3, 28),
    )

    assert [row["security_code"] for row in result["constituents"]] == ["700", "1810"]
    assert result["constituents"][0]["ticker"] == "0700.HK"
    assert result["constituents"][0]["source_codes"]["hsics_industry"] == "70"
    assert result["datasets"]["index_constituents"]["source_type"] == "DATAWAREHOUSE_SQLITE"
    assert result["datasets"]["index_constituents"]["lineage"]["effective_as_of"] == "2025-03-28"


def test_rejects_partial_mysql_configuration_instead_of_falling_back(tmp_path, monkeypatch):
    database = tmp_path / "warehouse.db"
    build_performance_snapshot(database)
    monkeypatch.setattr(settings, "datawarehouse_sqlite_path", database)
    monkeypatch.setattr(settings, "datawarehouse_mysql_host", "warehouse.internal")
    monkeypatch.setattr(settings, "datawarehouse_mysql_database", None)
    monkeypatch.setattr(settings, "datawarehouse_mysql_username", None)
    monkeypatch.setattr(settings, "datawarehouse_mysql_password", None)

    with pytest.raises(DataWarehouseProviderError) as raised:
        load_historical_performance(
            fund_ticker="3033.HK",
            benchmark_instrument_code="HSTECHN",
            report_date=date(2025, 3, 31),
            formula_version="warehouse-period-return-v1",
        )

    assert raised.value.code == "DATAWAREHOUSE_MYSQL_CONFIG_INCOMPLETE"


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


def test_does_not_use_an_earlier_month_when_selected_month_has_no_rows(tmp_path, monkeypatch):
    database = tmp_path / "warehouse.db"
    build_performance_snapshot(database)
    monkeypatch.setattr(settings, "datawarehouse_sqlite_path", database)
    monkeypatch.setattr(settings, "datawarehouse_sqlite_sha256", None)

    with pytest.raises(DataWarehouseProviderError) as raised:
        load_historical_performance(
            fund_ticker="3033.HK",
            benchmark_instrument_code="HSTECHN",
            report_date=date(2025, 4, 30),
            formula_version="warehouse-period-return-v1",
        )

    assert raised.value.code == "DATAWAREHOUSE_REPORT_MONTH_NOT_FOUND"
    assert "selected report month 2025-04" in raised.value.message
    assert "latest available month not later than the report date is 2025-03" in raised.value.message


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
    assert len(fragment["constituents"]) == 2
    assert fragment["datasets"]["index_constituents"]["source_type"] == "DATAWAREHOUSE_SQLITE"
