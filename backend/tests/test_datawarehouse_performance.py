import sqlite3
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.integrations import datawarehouse
from app.integrations.datawarehouse import (
    DataWarehouseProviderError,
    load_fund_aum,
    load_fund_kpis,
    load_historical_performance,
    load_index_constituents,
    load_report_month_index_constituents,
)
from app.domain import snapshot_composer


@pytest.fixture(autouse=True)
def isolate_live_cdb_configuration(monkeypatch):
    """Unit fixtures must never inherit credentials from the developer's local .env."""
    datawarehouse._clear_report_month_constituent_cache()
    monkeypatch.setattr(settings, "datawarehouse_mysql_host", None)
    monkeypatch.setattr(settings, "datawarehouse_mysql_database", None)
    monkeypatch.setattr(settings, "datawarehouse_mysql_username", None)
    monkeypatch.setattr(settings, "datawarehouse_mysql_password", None)
    monkeypatch.setattr(settings, "datawarehouse_mysql_ssl_ca", None)
    monkeypatch.setattr(settings, "datawarehouse_fund_aum_view", None)
    monkeypatch.setattr(settings, "datawarehouse_fund_kpi_view", None)
    yield
    datawarehouse._clear_report_month_constituent_cache()


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
        CREATE TABLE approved_fund_kpi_daily (
            product_code TEXT, as_of_date TEXT, is_trading_day INTEGER,
            aum NUMERIC, aum_currency TEXT, aum_unit TEXT,
            daily_turnover NUMERIC, turnover_currency TEXT, turnover_unit TEXT,
            source TEXT, updated_at TEXT
        );
        CREATE TABLE view_ads_busi_valuation_nav_fund_level_exposure_1_f_p (
            trade_date TEXT, tradar_code TEXT, fund_ccy TEXT, actual_nav_fc NUMERIC
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


def insert_fund_kpi_month(path, *, report_date: date, aum_date: date | None = None) -> None:
    connection = sqlite3.connect(path)
    current = report_date.replace(day=1)
    rows = []
    while current <= report_date:
        is_trading_day = current.weekday() < 5
        rows.append((
            "3033",
            current.isoformat(),
            is_trading_day,
            "67536553763.03" if current == (aum_date or report_date) else None,
            "HKD" if current == (aum_date or report_date) else None,
            "unit" if current == (aum_date or report_date) else None,
            "12882" if is_trading_day else None,
            "HKD" if is_trading_day else None,
            "million" if is_trading_day else None,
            "Approved CDB KPI",
            "2026-07-01T00:00:00Z",
        ))
        current += timedelta(days=1)
    connection.executemany(
        "INSERT INTO approved_fund_kpi_daily VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
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


def test_loads_cdb_fund_kpis_with_latest_same_month_aum_and_calendar(tmp_path, monkeypatch):
    database = tmp_path / "warehouse.db"
    build_performance_snapshot(database)
    insert_fund_kpi_month(
        database,
        report_date=date(2026, 6, 30),
        aum_date=date(2026, 6, 29),
    )
    monkeypatch.setattr(settings, "datawarehouse_sqlite_path", database)
    monkeypatch.setattr(settings, "datawarehouse_sqlite_sha256", None)
    monkeypatch.setattr(settings, "datawarehouse_fund_kpi_view", "approved_fund_kpi_daily")

    result = load_fund_kpis(
        product_code="3033",
        trading_calendar_code="HK",
        report_date=date(2026, 6, 30),
    )

    aum = [row for row in result["fund_kpis"] if row["metric_code"] == "AUM"]
    turnover = [row for row in result["fund_kpis"] if row["metric_code"] == "DAILY_TURNOVER"]
    assert aum == [{
        "metric_code": "AUM",
        "metric_date": "2026-06-29",
        "value": "67536553763.03",
        "unit": "unit",
        "currency": "HKD",
        "source": "Approved CDB KPI",
    }]
    assert len(turnover) == 22
    assert len(result["trading_calendar"]) == 30
    assert result["datasets"]["fund_kpi_daily"]["mapping_version"] == "cdb-fund-kpi-v1"
    assert result["datasets"]["fund_kpi_daily"]["lineage"]["effective_as_of"] == "2026-06-29"
    assert not result["_findings"]


def test_loads_latest_report_month_aum_from_existing_cdb_view(tmp_path, monkeypatch):
    database = tmp_path / "warehouse.db"
    build_performance_snapshot(database)
    connection = sqlite3.connect(database)
    connection.executemany(
        "INSERT INTO view_ads_busi_valuation_nav_fund_level_exposure_1_f_p VALUES (?, ?, ?, ?)",
        [
            ("2026-06-29", "CO-CHST", "HKD", "68000000000"),
            ("2026-06-30", "CO-CHST", "HKD", "67536553763.03"),
        ],
    )
    connection.commit()
    connection.close()
    monkeypatch.setattr(settings, "datawarehouse_sqlite_path", database)
    monkeypatch.setattr(settings, "datawarehouse_sqlite_sha256", None)
    monkeypatch.setattr(
        settings,
        "datawarehouse_fund_aum_view",
        "view_ads_busi_valuation_nav_fund_level_exposure_1_f_p",
    )

    result = load_fund_aum(
        fund_ticker="3033.HK",
        product_code="3033",
        report_date=date(2026, 6, 30),
    )

    assert result["fund_kpis"] == [{
        "metric_code": "AUM",
        "metric_date": "2026-06-30",
        "value": "67536553763.03",
        "unit": "unit",
        "currency": "HKD",
        "source": "CSOP Data Warehouse fund-level valuation",
    }]
    metadata = result["datasets"]["fund_kpi_daily"]
    assert metadata["mapping_version"] == "cdb-fund-aum-v1"
    assert metadata["lineage"]["source_record_keys"] == ["CO-CHST:2026-06-30"]
    assert [item["check_id"] for item in result["_findings"]] == [
        "DATAWAREHOUSE_TURNOVER_VIEW_NOT_CONFIGURED"
    ]


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        ("duplicate", "DATAWAREHOUSE_FUND_KPI_DUPLICATE"),
        ("negative", "DATAWAREHOUSE_FUND_KPI_INVALID"),
        ("bad_unit", "DATAWAREHOUSE_FUND_KPI_INVALID"),
        ("missing_date", "DATAWAREHOUSE_FUND_KPI_CALENDAR_INCOMPLETE"),
    ],
)
def test_rejects_invalid_cdb_fund_kpi_contract(tmp_path, monkeypatch, mutation, expected_code):
    database = tmp_path / "warehouse.db"
    build_performance_snapshot(database)
    insert_fund_kpi_month(database, report_date=date(2026, 6, 30))
    connection = sqlite3.connect(database)
    if mutation == "duplicate":
        connection.execute(
            "INSERT INTO approved_fund_kpi_daily SELECT * FROM approved_fund_kpi_daily WHERE as_of_date='2026-06-30'"
        )
    elif mutation == "negative":
        connection.execute(
            "UPDATE approved_fund_kpi_daily SET daily_turnover=-1 WHERE as_of_date='2026-06-01'"
        )
    elif mutation == "bad_unit":
        connection.execute(
            "UPDATE approved_fund_kpi_daily SET turnover_unit='lots' WHERE as_of_date='2026-06-01'"
        )
    else:
        connection.execute("DELETE FROM approved_fund_kpi_daily WHERE as_of_date='2026-06-15'")
    connection.commit()
    connection.close()
    monkeypatch.setattr(settings, "datawarehouse_sqlite_path", database)
    monkeypatch.setattr(settings, "datawarehouse_sqlite_sha256", None)
    monkeypatch.setattr(settings, "datawarehouse_fund_kpi_view", "approved_fund_kpi_daily")

    with pytest.raises(DataWarehouseProviderError) as raised:
        load_fund_kpis(
            product_code="3033",
            trading_calendar_code="HK",
            report_date=date(2026, 6, 30),
        )

    assert raised.value.code == expected_code


def test_reports_missing_cdb_fund_kpi_view_as_schema_mismatch(tmp_path, monkeypatch):
    database = tmp_path / "warehouse.db"
    build_performance_snapshot(database)
    monkeypatch.setattr(settings, "datawarehouse_sqlite_path", database)
    monkeypatch.setattr(settings, "datawarehouse_sqlite_sha256", None)
    monkeypatch.setattr(settings, "datawarehouse_fund_kpi_view", "missing_fund_kpi_view")

    with pytest.raises(DataWarehouseProviderError) as raised:
        load_fund_kpis(
            product_code="3033",
            trading_calendar_code="HK",
            report_date=date(2026, 6, 30),
        )

    assert raised.value.code == "DATAWAREHOUSE_SCHEMA_MISMATCH"


def test_reports_cdb_fund_kpi_field_drift_as_schema_mismatch(tmp_path, monkeypatch):
    database = tmp_path / "warehouse.db"
    build_performance_snapshot(database)
    monkeypatch.setattr(settings, "datawarehouse_sqlite_path", database)
    monkeypatch.setattr(settings, "datawarehouse_sqlite_sha256", None)
    monkeypatch.setattr(
        settings,
        "datawarehouse_fund_kpi_view",
        "view_ads_busi_product_fundinfo_class_f_p",
    )

    with pytest.raises(DataWarehouseProviderError) as raised:
        load_fund_kpis(
            product_code="3033",
            trading_calendar_code="HK",
            report_date=date(2026, 6, 30),
        )

    assert raised.value.code == "DATAWAREHOUSE_SCHEMA_MISMATCH"
    assert "daily_turnover" in raised.value.message


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


def test_loads_and_caches_latest_index_constituents_inside_report_month(tmp_path, monkeypatch):
    database = tmp_path / "warehouse.db"
    build_performance_snapshot(database)
    monkeypatch.setattr(settings, "datawarehouse_sqlite_path", database)
    monkeypatch.setattr(settings, "datawarehouse_sqlite_sha256", None)

    first = load_report_month_index_constituents(
        index_code="HSTECH",
        report_date=date(2025, 3, 31),
    )
    connection = sqlite3.connect(database)
    connection.execute("DELETE FROM view_ads_busi_market_index_constituent_price_daily_f_p")
    connection.commit()
    connection.close()
    cached = load_report_month_index_constituents(
        index_code="HSTECH",
        report_date=date(2025, 3, 31),
    )

    assert first["effective_as_of"] == "2025-03-28"
    assert [row["security_code"] for row in first["constituents"]] == ["700", "1810"]
    assert cached == first


def test_report_month_constituents_do_not_fall_back_to_an_earlier_month(tmp_path, monkeypatch):
    database = tmp_path / "warehouse.db"
    build_performance_snapshot(database)
    monkeypatch.setattr(settings, "datawarehouse_sqlite_path", database)
    monkeypatch.setattr(settings, "datawarehouse_sqlite_sha256", None)

    with pytest.raises(DataWarehouseProviderError) as raised:
        load_report_month_index_constituents(
            index_code="HSTECH",
            report_date=date(2025, 4, 30),
        )

    assert raised.value.code == "DATAWAREHOUSE_CONSTITUENTS_NOT_FOUND"


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


def test_composer_prefers_configured_cdb_kpis_over_legacy_da_report(monkeypatch):
    monkeypatch.setattr(settings, "datawarehouse_performance_enabled", False)
    monkeypatch.setattr(settings, "datawarehouse_fund_kpi_view", "approved_fund_kpi_daily")
    monkeypatch.setattr(snapshot_composer, "load_monthly_data", lambda **kwargs: {
        "fund_kpis": [{"metric_code": "AUM", "value": "1", "source": "Legacy"}],
        "trading_calendar": [{"date": "2026-06-30", "is_trading_day": True, "source": "Legacy"}],
        "datasets": {
            "fund_kpi_daily": {"source_type": "DA_REPORT_SQLITE"},
            "trading_calendar": {"source_type": "DA_REPORT_SQLITE"},
        },
        "_findings": [],
    })
    monkeypatch.setattr(snapshot_composer, "load_fund_kpis", lambda **kwargs: {
        "fund_kpis": [{"metric_code": "AUM", "value": "2", "source": "CDB"}],
        "trading_calendar": [{"date": "2026-06-30", "is_trading_day": True, "source": "CDB"}],
        "datasets": {
            "fund_kpi_daily": {"source_type": "CDB_MYSQL"},
            "trading_calendar": {"source_type": "CDB_MYSQL"},
        },
        "_findings": [],
    })
    product = SimpleNamespace(
        product_code="3033",
        ticker="3033.HK",
        benchmark_instrument_code="HSTECHN",
        formula_profile="warehouse-period-return-v1",
        fund_total_return_instrument_code="3033.HK",
        fund_kpi_product_code="3033",
        trading_calendar_code="HK",
        constituent_index_code="HSTECH",
    )

    fragment, findings = snapshot_composer.compose_da_report_fragment(product, date(2026, 6, 30))

    assert not findings
    assert fragment["fund_kpis"][0]["value"] == "2"
    assert fragment["datasets"]["fund_kpi_daily"]["source_type"] == "CDB_MYSQL"
    assert fragment["datasets"]["trading_calendar"]["source_type"] == "CDB_MYSQL"


def test_composer_never_falls_back_to_da_report_after_configured_cdb_kpi_failure(monkeypatch):
    monkeypatch.setattr(settings, "datawarehouse_performance_enabled", False)
    monkeypatch.setattr(settings, "datawarehouse_fund_kpi_view", "approved_fund_kpi_daily")
    monkeypatch.setattr(snapshot_composer, "load_monthly_data", lambda **kwargs: {
        "fund_kpis": [{"metric_code": "AUM", "value": "1", "source": "Legacy"}],
        "trading_calendar": [{"date": "2026-06-30", "is_trading_day": True, "source": "Legacy"}],
        "datasets": {
            "fund_kpi_daily": {"source_type": "DA_REPORT_SQLITE"},
            "trading_calendar": {"source_type": "DA_REPORT_SQLITE"},
        },
        "_findings": [],
    })

    def fail(**kwargs):
        raise DataWarehouseProviderError("DATAWAREHOUSE_FUND_KPI_QUERY_FAILED", "unavailable")

    monkeypatch.setattr(snapshot_composer, "load_fund_kpis", fail)
    product = SimpleNamespace(
        product_code="3033",
        ticker="3033.HK",
        benchmark_instrument_code="HSTECHN",
        formula_profile="warehouse-period-return-v1",
        fund_total_return_instrument_code="3033.HK",
        fund_kpi_product_code="3033",
        trading_calendar_code="HK",
        constituent_index_code="HSTECH",
    )

    fragment, findings = snapshot_composer.compose_da_report_fragment(product, date(2026, 6, 30))

    assert "fund_kpis" not in fragment
    assert "trading_calendar" not in fragment
    assert "fund_kpi_daily" not in fragment["datasets"]
    assert "trading_calendar" not in fragment["datasets"]
    assert [finding["check_id"] for finding in findings] == ["DATAWAREHOUSE_FUND_KPI_QUERY_FAILED"]


def test_composer_uses_cdb_aum_bridge_without_mixing_legacy_turnover(monkeypatch):
    monkeypatch.setattr(settings, "datawarehouse_performance_enabled", False)
    monkeypatch.setattr(settings, "datawarehouse_fund_kpi_view", None)
    monkeypatch.setattr(settings, "datawarehouse_fund_aum_view", "approved_fund_aum")
    monkeypatch.setattr(snapshot_composer, "load_monthly_data", lambda **kwargs: {
        "fund_kpis": [
            {"metric_code": "AUM", "value": "1", "source": "Legacy"},
            {"metric_code": "DAILY_TURNOVER", "value": "99", "source": "Legacy"},
        ],
        "trading_calendar": [{"date": "2026-06-30", "is_trading_day": True, "source": "Legacy"}],
        "datasets": {
            "fund_kpi_daily": {"source_type": "DA_REPORT_SQLITE"},
            "trading_calendar": {"source_type": "DA_REPORT_SQLITE"},
        },
        "_findings": [],
    })
    monkeypatch.setattr(snapshot_composer, "load_fund_aum", lambda **kwargs: {
        "fund_kpis": [{"metric_code": "AUM", "value": "2", "source": "CDB"}],
        "datasets": {"fund_kpi_daily": {"source_type": "CDB_MYSQL"}},
        "_findings": [{"check_id": "DATAWAREHOUSE_TURNOVER_VIEW_NOT_CONFIGURED"}],
    })
    def no_monthly_turnover(**kwargs):
        raise snapshot_composer.DaReportProviderError(
            "DA_REPORT_MONTHLY_TURNOVER_NOT_AVAILABLE", "not available", 404,
        )

    monkeypatch.setattr(snapshot_composer, "load_monthly_turnover", no_monthly_turnover)
    product = SimpleNamespace(
        product_code="3033",
        ticker="3033.HK",
        benchmark_instrument_code="HSTECHN",
        formula_profile="warehouse-period-return-v1",
        fund_total_return_instrument_code="3033.HK",
        fund_kpi_product_code="3033",
        trading_calendar_code="HK",
        constituent_index_code="HSTECH",
    )

    fragment, findings = snapshot_composer.compose_da_report_fragment(product, date(2026, 6, 30))

    assert fragment["fund_kpis"] == [{"metric_code": "AUM", "value": "2", "source": "CDB"}]
    assert "trading_calendar" not in fragment
    assert fragment["datasets"]["fund_kpi_daily"]["source_type"] == "CDB_MYSQL"
    assert "trading_calendar" not in fragment["datasets"]
    assert [finding["check_id"] for finding in findings] == ["DATAWAREHOUSE_TURNOVER_VIEW_NOT_CONFIGURED"]


def test_composer_combines_cdb_aum_with_separately_lineaged_bloomberg_monthly_turnover(monkeypatch):
    monkeypatch.setattr(settings, "datawarehouse_performance_enabled", False)
    monkeypatch.setattr(settings, "datawarehouse_fund_kpi_view", None)
    monkeypatch.setattr(settings, "datawarehouse_fund_aum_view", "approved_fund_aum")
    monkeypatch.setattr(snapshot_composer, "load_monthly_data", lambda **kwargs: {
        "datasets": {},
        "_findings": [],
    })
    monkeypatch.setattr(snapshot_composer, "load_fund_aum", lambda **kwargs: {
        "fund_kpis": [{
            "metric_code": "AUM", "metric_date": "2026-06-30", "value": "67536550000",
            "unit": "unit", "currency": "HKD", "source": "CDB",
        }],
        "datasets": {"fund_kpi_daily": {"source_type": "CDB_MYSQL"}},
        "_findings": [{"check_id": "DATAWAREHOUSE_TURNOVER_VIEW_NOT_CONFIGURED"}],
    })
    monthly_row = {
        "period_start": "2026-06-01", "period_end": "2026-06-30",
        "total_turnover": "270532410000", "trading_days": 21,
        "average_daily_turnover": "12882495714.28571428571428571",
        "currency": "HKD", "unit": "unit", "source": "Bloomberg",
    }
    monkeypatch.setattr(snapshot_composer, "load_monthly_turnover", lambda **kwargs: {
        "fund_turnover_monthly": [monthly_row],
        "datasets": {"fund_turnover_monthly": {"source_type": "DA_REPORT_SQLITE"}},
    })
    product = SimpleNamespace(
        product_code="3033",
        ticker="3033.HK",
        benchmark_instrument_code="HSTECHN",
        formula_profile="warehouse-period-return-v1",
        fund_total_return_instrument_code="3033.HK",
        fund_kpi_product_code="3033",
        trading_calendar_code="HK",
        constituent_index_code="HSTECH",
    )

    fragment, findings = snapshot_composer.compose_da_report_fragment(product, date(2026, 6, 30))

    assert fragment["fund_kpis"][0]["source"] == "CDB"
    assert fragment["fund_turnover_monthly"] == [monthly_row]
    assert fragment["datasets"]["fund_turnover_monthly"]["source_type"] == "DA_REPORT_SQLITE"
    assert not findings
