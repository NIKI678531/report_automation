"""MySQL adapter contract. Live fixtures require an explicitly isolated localhost test schema."""
import asyncio
from datetime import date, datetime
import json
import os
from pathlib import Path
import sqlite3
import ssl

import pytest
from sqlalchemy import Column, Date, DateTime, Double, Integer, MetaData, Table, Text, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError, SQLAlchemyError

from app.core.config import settings
from app.integrations import da_report as da
from test_da_report_news import build_da_snapshot
from test_da_report_monthly import build_monthly_snapshot, build_monthly_turnover_snapshot


@pytest.mark.parametrize("url", ["not-a-url", "sqlite:///local.db", "mysql://user:private@db/da", "mysql+pymysql://user:private@db:private/da", "mysql+pymysql://user:private@db/da?local_infile=1"])
def test_invalid_mysql_settings_fail_closed_without_credentials(url, monkeypatch):
    monkeypatch.setattr(settings, "da_report_database_url", url)
    problems = settings.da_report_mysql_problems()
    assert problems and "private" not in str(problems)
    assert not da.is_configured()
    monkeypatch.setattr(da, "_materialize_snapshot", lambda: pytest.fail("unexpected SQLite fallback"))
    with pytest.raises(da.DaReportProviderError, match="configuration"):
        da._data_source()


def test_mysql_failure_does_not_use_sqlite_or_expose_connection(monkeypatch):
    monkeypatch.setattr(settings, "da_report_database_url", "mysql+pymysql://reader:private@db.invalid/da")
    class BrokenEngine:
        def connect(self):
            raise OperationalError("SELECT", {}, Exception("private database credentials"))
    monkeypatch.setattr(da, "_mysql_engine", lambda *args: BrokenEngine())
    monkeypatch.setattr(da, "_materialize_snapshot", lambda: pytest.fail("unexpected SQLite fallback"))
    with pytest.raises(da.DaReportProviderError) as failure:
        da.load_monthly_turnover(product_ticker="3033.HK", report_date=date(2026, 6, 30))
    assert failure.value.code == "DA_REPORT_UNAVAILABLE"
    assert "private" not in str(failure.value)
    assert failure.value.__suppress_context__


def test_deployed_mysql_requires_hostname_verification(monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "REMOTE")
    monkeypatch.setattr(settings, "da_report_database_url", "mysql+pymysql://reader:test@db.invalid/da")
    monkeypatch.setattr(settings, "da_report_mysql_ssl_verify_identity", False)
    assert any("SSL_VERIFY_IDENTITY" in problem for problem in settings.deployment_problems())


@pytest.fixture(scope="module")
def mysql_contract(tmp_path_factory):
    raw = os.getenv("TEST_DA_REPORT_MYSQL_URL")
    ca = os.getenv("TEST_DA_REPORT_MYSQL_CA")
    if not raw or not ca:
        pytest.skip("Set TEST_DA_REPORT_MYSQL_URL and TEST_DA_REPORT_MYSQL_CA for an isolated MySQL contract database")
    url = make_url(raw)
    # This suite creates fixture tables. A production DA_REPORT_DATABASE_URL is never accepted.
    if url.database != "da_contract" or url.host not in {"127.0.0.1", "localhost"}:
        pytest.fail("MySQL contract fixture requires localhost and the disposable da_contract schema")
    tls = ssl.create_default_context(cafile=ca)
    tls.check_hostname = False
    tls.verify_flags &= ~ssl.VERIFY_X509_STRICT
    kwargs = {"connect_args": {"ssl": tls, "charset": "utf8mb4"}}
    admin = create_engine(url.set(database=None), **kwargs)
    with admin.begin() as connection:
        connection.execute(text("CREATE DATABASE IF NOT EXISTS da_contract CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"))
    admin.dispose()
    writer = create_engine(url, **kwargs)
    path = tmp_path_factory.mktemp("da-mysql") / "source.sqlite"
    build_da_snapshot(path)
    build_monthly_snapshot(path)
    build_monthly_turnover_snapshot(path)
    schema = MetaData()
    dates = {"trade_date", "metric_date", "announcement_date", "effective_date", "month_start", "period_start", "period_end"}
    with sqlite3.connect(path) as db:
        db.row_factory = sqlite3.Row
        tables = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        for name in tables:
            columns = []
            for row in db.execute(f"PRAGMA table_info({name})"):
                key = row["name"]
                kind = DateTime if key.endswith("_at") else Date if key in dates else Integer if row["type"] == "INTEGER" else Double if row["type"] == "REAL" else Text
                columns.append(Column(key, kind(), primary_key=bool(row["pk"])))
            Table(name, schema, *columns)
        # Only the known fixture tables in the guarded disposable schema are touched.
        schema.drop_all(writer)
        schema.create_all(writer)
        for name in tables:
            rows = [dict(row) for row in db.execute(f"SELECT * FROM {name}")]
            for row in rows:
                for key, value in row.items():
                    if value and key.endswith("_at"):
                        row[key] = datetime.fromisoformat(value)
                    elif value and key in dates:
                        row[key] = date.fromisoformat(value)
            with writer.begin() as connection:
                connection.execute(schema.tables[name].insert(), rows)
    try:
        yield raw, ca, path
    finally:
        for engine in [da._mysql_engine(raw, 10, ca, False), writer]:
            engine.dispose()
        schema.drop_all(writer)
        writer.dispose()
        da._mysql_engine.cache_clear()


@pytest.fixture
def mysql_source(mysql_contract, monkeypatch):
    raw, ca, path = mysql_contract
    monkeypatch.setattr(settings, "auth_mode", "LOCAL")
    monkeypatch.setattr(settings, "da_report_database_url", raw)
    monkeypatch.setattr(settings, "da_report_mysql_ssl_ca", Path(ca))
    monkeypatch.setattr(settings, "da_report_mysql_ssl_verify_identity", False)
    monkeypatch.setattr(settings, "da_report_timeout_seconds", 10)
    monkeypatch.setattr(settings, "da_report_sqlite_path", path)
    monkeypatch.setattr(settings, "da_report_sqlite_sha256", None)
    return da._data_source()


def test_mysql_news_search_facets_selection_and_keyset_pagination(mysql_source):
    first = asyncio.run(da.list_company_news_catalog(limit=2))
    second = asyncio.run(da.list_company_news_catalog(limit=2, cursor=first["next_cursor"]))
    assert [item["external_id"] for item in first["items"] + second["items"]] == ["5", "2", "1", "6"]
    assert first["total"] == 4
    assert first["facets"]["sentiments"] == {"neutral": 2, "bear": 1, "bull": 1}
    filtered = asyncio.run(da.list_company_news_catalog(query="Tencent", from_date=date(2026, 6, 1), to_date=date(2026, 6, 30), sort="oldest"))
    assert [item["external_id"] for item in filtered["items"]] == ["1"]
    item = asyncio.run(da.get_company_news_catalog_item("1"))
    assert item["title"] == "Tencent raises its outlook"
    json.dumps({"fetched_at": item["fetched_at"]})  # MySQL DATETIME must not leak into persisted JSON.
    with pytest.raises(da.DaReportProviderError):
        asyncio.run(da.get_company_news_catalog_item("4"))
    with pytest.raises(da.DaReportProviderError):
        asyncio.run(da.list_company_news_catalog(query="changed", cursor=first["next_cursor"]))


@pytest.mark.parametrize(("title", "alias"), [
    ("NIO launches a new model", "NIO"), ("A senior executive comments", "NIO"),
    ("騰訊控股公布季度業績", "騰訊控股"), ("腾讯发布消息", "腾讯"),
    ("0700.HK rises", "0700.HK"), ("ＴＥＮＣＥＮＴ rises", "TENCENT"),
    ("Tencent-SW announces", "Tencent-SW"), ("a NIO2 vehicle", "NIO"),
])
def test_mysql_company_matching_agrees_with_sqlite(mysql_source, title, alias):
    parameters = {"title": title}
    predicate = da._company_predicate(mysql_source, ":title", "alias", alias, parameters)
    with mysql_source.engine.connect() as connection:
        actual = connection.execute(text("SELECT " + predicate), parameters).scalar_one()
    assert bool(actual) == bool(da._sqlite_contains_company_alias(title, alias))


def test_mysql_constituent_catalog_and_candidates(mysql_source):
    constituents = [{"security_code": "700", "ticker": "0700.HK", "name_en": "TENCENT", "name_zh_hant": "騰訊控股"}]
    catalog = asyncio.run(da.list_company_news_catalog(constituents=constituents, company_scope="CONSTITUENTS"))
    assert [row["external_id"] for row in catalog["items"]] == ["5", "1", "6"]
    candidates = asyncio.run(da.fetch_news("CONSTITUENTS", [], date(2026, 6, 1), date(2026, 6, 30), 0, 20, constituents=constituents))
    assert len(candidates) == 1
    json.dumps(candidates[0]["metadata_json"])


def test_mysql_monthly_dates_lineage_and_turnover(mysql_source):
    payload = da.load_monthly_data(product_code="3033", fund_instrument_code="3033.HK", benchmark_instrument_code="HSTECHN", trading_calendar_code="HK", constituent_index_code="HSTECH", report_date=date(2026, 6, 30))
    assert len(payload["total_return_series"]) == 6
    assert len(payload["source_checksum"]) == 64
    metadata = payload["datasets"]["total_return_series"]
    assert metadata["source_type"] == "DA_REPORT_MYSQL"
    assert "sqlite_checksum" not in metadata["lineage"]
    assert metadata["lineage"]["source_record_ids"]
    json.dumps(payload)
    repeated = da.load_monthly_data(product_code="3033", fund_instrument_code="3033.HK", benchmark_instrument_code="HSTECHN", trading_calendar_code="HK", constituent_index_code="HSTECH", report_date=date(2026, 6, 30))
    assert payload == repeated
    turnover = da.load_monthly_turnover(product_ticker="3033.HK", report_date=date(2026, 6, 30))
    assert turnover["fund_turnover_monthly"][0]["trading_days"] == 21
    assert turnover["datasets"]["fund_turnover_monthly"]["source_type"] == "DA_REPORT_MYSQL"


def test_mysql_session_enforces_read_only_and_limits(mysql_source):
    with mysql_source.engine.connect() as connection:
        assert connection.execute(text("SELECT @@transaction_read_only")).scalar_one() == 1
        assert connection.execute(text("SELECT @@max_execution_time")).scalar_one() == 10000
        assert connection.execute(text("SHOW SESSION STATUS LIKE 'Ssl_cipher'")).one()[1]
        with pytest.raises(SQLAlchemyError):
            connection.execute(text("UPDATE news_items SET title_raw='must not write' WHERE id=1"))
