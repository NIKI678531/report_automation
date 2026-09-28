"""Migrations, and the schema properties that only bite on MySQL.

The suite runs against SQLite because that is what every developer and CI job has. SQLite is,
however, permissive in exactly the places MySQL is not - it will happily index a 1000-character
column that InnoDB refuses outright - so the checks below read the *declared* metadata rather than
the created SQLite objects wherever the two engines disagree. Point ``TEST_MYSQL_URL`` at a
throwaway MySQL 8 database to run the same migrations against the real target.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import String, create_engine, inspect, text

from app.core.database import Base
from app.domain import models  # noqa: F401 - imported for its side effect of registering tables

BACKEND_ROOT = Path(__file__).parents[1]

EXPECTED_TABLES = {
    "reports", "report_documents", "data_snapshots", "snapshot_datasets", "data_imports", "import_batches",
    "mapping_profiles", "metric_values", "module_snapshots", "quality_check_results", "render_jobs",
    "industry_master", "render_artifacts", "audit_events", "news_items", "report_news_candidates",
    "news_fetch_runs", "report_news_selections",
}

# InnoDB caps an index key at 3072 bytes, and utf8mb4 reserves four bytes per character. A
# VARCHAR(1000) unique column is therefore 4000 bytes and fails at CREATE TABLE time - which is how
# `news_items.source_url` once made a fresh MySQL install unreachable from migration 12 onwards.
MAX_UTF8MB4_INDEX_CHARS = 3072 // 4


def _config(url: str) -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config


@pytest.fixture()
def sqlite_url(tmp_path) -> str:
    return f"sqlite:///{(tmp_path / 'migration.db').as_posix()}"


def test_initial_migration_upgrade_and_downgrade(sqlite_url):
    config = _config(sqlite_url)
    command.upgrade(config, "head")
    engine = create_engine(sqlite_url)
    tables = set(inspect(engine).get_table_names())
    assert EXPECTED_TABLES.issubset(tables)
    assert "batch_id" in {column["name"] for column in inspect(engine).get_columns("data_imports")}
    assert {"language_mode", "translation_source_report_id"}.issubset(
        {column["name"] for column in inspect(engine).get_columns("reports")}
    )
    assert "source_snapshot_id" in {
        column["name"] for column in inspect(engine).get_columns("data_snapshots")
    }
    assert "name_zh_hans" in {
        column["name"] for column in inspect(engine).get_columns("product_catalog")
    }
    assert "name_zh_hans" in {
        column["name"] for column in inspect(engine).get_columns("industry_master")
    }
    with engine.connect() as connection:
        products = connection.execute(text("SELECT product_code, ticker, name_en FROM product_catalog ORDER BY display_order")).all()
        bindings = connection.execute(text("SELECT fund_total_return_instrument_code, fund_kpi_product_code, trading_calendar_code, template_version, design_token_version FROM product_catalog WHERE product_code = '3033'")).one()
        profiles = dict(connection.execute(text("SELECT profile_id, status FROM mapping_profiles")).all())
    assert ("3037", "3037.HK", "CSOP Hang Seng Index ETF") in products
    assert ("3535", "3535.HK", "CSOP Nomura FTSE HK-Japan Equity Cash Flow ETF") in products
    assert bindings == ("3033.HK", "3033", "HK", "3033-v3", "3033-v3")
    assert profiles["standard_constituent_returns_csv"] == "APPROVED"
    assert profiles["standard_total_return_series_csv"] == "APPROVED"
    assert profiles["standard_fund_kpi_daily_csv"] == "APPROVED"
    assert profiles["standard_trading_calendar_csv"] == "APPROVED"
    assert profiles["bloomberg_gics_reference"] == "DRAFT"
    assert profiles["approved_sector_overrides"] == "DRAFT"
    command.check(config)
    command.downgrade(config, "base")
    assert set(inspect(engine).get_table_names()) == {"alembic_version"}


def test_every_revision_applies_one_at_a_time(sqlite_url):
    """`upgrade head` runs the chain in one transaction per revision but only reports the end.

    Stepping revision by revision is what catches a migration that only succeeds because a later
    one repairs it - and, on a fresh deployment, that is the failure that leaves the database
    stranded halfway with no way forward.
    """
    config = _config(sqlite_url)
    revisions = list(ScriptDirectory.from_config(config).walk_revisions())
    assert len(revisions) > 1
    for _ in revisions:
        command.upgrade(config, "+1")
    engine = create_engine(sqlite_url)
    assert EXPECTED_TABLES.issubset(set(inspect(engine).get_table_names()))
    with engine.connect() as connection:
        head = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert head == ScriptDirectory.from_config(config).get_current_head()


def test_every_revision_reverses_one_at_a_time(sqlite_url):
    """A downgrade nobody runs is a downgrade that does not work when a release has to be rolled
    back. Each step is exercised individually so a broken one names itself."""
    config = _config(sqlite_url)
    command.upgrade(config, "head")
    revisions = list(ScriptDirectory.from_config(config).walk_revisions())
    for _ in revisions:
        command.downgrade(config, "-1")
    engine = create_engine(sqlite_url)
    assert set(inspect(engine).get_table_names()) == {"alembic_version"}


def test_the_schema_survives_a_downgrade_and_re_upgrade(sqlite_url):
    """A rollback followed by a re-deploy has to land on the same schema, not a near-miss."""
    config = _config(sqlite_url)
    command.upgrade(config, "head")
    engine = create_engine(sqlite_url)
    before = {table: sorted(column["name"] for column in inspect(engine).get_columns(table))
              for table in sorted(inspect(engine).get_table_names())}
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    after = {table: sorted(column["name"] for column in inspect(engine).get_columns(table))
             for table in sorted(inspect(engine).get_table_names())}
    assert after == before
    # The re-created schema must still match the ORM, not merely match itself.
    command.check(config)


def _indexed_string_columns():
    """Every (table, index name, column) pair whose key includes a variable-length string."""
    for table in Base.metadata.sorted_tables:
        keys: list[tuple[str, list]] = [
            (index.name or "<unnamed index>", list(index.columns)) for index in table.indexes
        ]
        for constraint in table.constraints:
            columns = getattr(constraint, "columns", None)
            if columns is not None and constraint.__class__.__name__ in {"UniqueConstraint", "PrimaryKeyConstraint"}:
                keys.append((constraint.name or f"<unnamed {constraint.__class__.__name__}>", list(columns)))
        for name, columns in keys:
            for column in columns:
                if isinstance(column.type, String):
                    yield table.name, name, column.name, column.type.length


def test_no_index_key_exceeds_the_innodb_limit():
    """MySQL refuses the CREATE TABLE outright, so this is a deployment blocker, not a warning."""
    oversized = [
        f"{table}.{column} ({length} chars) in {index}"
        for table, index, column, length in _indexed_string_columns()
        if length is not None and length > MAX_UTF8MB4_INDEX_CHARS
    ]
    assert not oversized, (
        "utf8mb4 indexes are capped at "
        f"{MAX_UTF8MB4_INDEX_CHARS} characters (3072 bytes) on InnoDB: " + "; ".join(oversized)
    )


def test_indexed_string_columns_declare_a_length():
    """An unbounded String becomes TEXT on MySQL, which cannot be indexed without a prefix."""
    unbounded = [
        f"{table}.{column} in {index}"
        for table, index, column, length in _indexed_string_columns()
        if length is None
    ]
    assert not unbounded


def test_long_urls_are_deduplicated_by_hash_rather_than_by_the_url_itself():
    """The uniqueness the application needs is on a 1000-character URL, which InnoDB cannot index.

    Hashing moves the constraint onto a fixed 64-character column and keeps the full URL readable.
    """
    news = Base.metadata.tables["news_items"]
    assert news.c.source_url.type.length is not None
    assert not news.c.source_url.unique
    unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in news.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert ("source_url_hash",) in unique_columns


# --------------------------------------------------------------------------------------------
# Opt-in: the real target
# --------------------------------------------------------------------------------------------

MYSQL_URL = os.getenv("TEST_MYSQL_URL")


@pytest.mark.skipif(not MYSQL_URL, reason="set TEST_MYSQL_URL to a throwaway MySQL 8 database")
def test_migrations_apply_to_a_real_mysql_database():
    """SQLite accepts DDL MySQL rejects; this is the run that proves a deployment can start.

    Destructive: it downgrades the target to base first, which is why it is opt-in and must point
    at a scratch database.
    """
    config = _config(MYSQL_URL)
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    engine = create_engine(MYSQL_URL)
    inspector = inspect(engine)
    assert EXPECTED_TABLES.issubset(set(inspector.get_table_names()))
    with engine.connect() as connection:
        charsets = connection.execute(text(
            "SELECT DISTINCT character_set_name FROM information_schema.columns "
            "WHERE table_schema = DATABASE() AND character_set_name IS NOT NULL"
        )).scalars().all()
    # Legacy three-byte `utf8` silently truncates the Traditional Chinese in a report.
    assert set(charsets) == {"utf8mb4"}, charsets
    command.check(config)
    command.downgrade(config, "base")


def test_migration_runtime_url_preserves_percent_encoded_password_without_connecting(monkeypatch):
    import runpy
    from unittest.mock import patch
    from app.core.config import settings

    url = "mysql+pymysql://user:encoded%40password%25@db.invalid/app?charset=utf8mb4"
    config = Config()
    config.set_main_option("sqlalchemy.url", "")
    monkeypatch.setattr(settings, "database_url", url)
    with patch("alembic.context.config", config, create=True), \
         patch("alembic.context.is_offline_mode", return_value=True), \
         patch("alembic.context.configure") as configure, \
         patch("alembic.context.begin_transaction"), \
         patch("alembic.context.run_migrations"):
        runpy.run_path(str(BACKEND_ROOT / "migrations" / "env.py"))
    assert configure.call_args.kwargs["url"] == url
