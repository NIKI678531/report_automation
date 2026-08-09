from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


def test_initial_migration_upgrade_and_downgrade(tmp_path):
    database = tmp_path / "migration.db"
    config = Config(str(__import__("pathlib").Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("script_location", str(__import__("pathlib").Path(__file__).parents[1] / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database.as_posix()}")
    command.upgrade(config, "head")
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    tables = set(inspect(engine).get_table_names())
    assert {"reports", "report_documents", "data_snapshots", "data_imports", "render_jobs", "render_artifacts", "audit_events", "news_items", "report_news_selections"}.issubset(tables)
    with engine.connect() as connection:
        products = connection.execute(text("SELECT product_code, ticker, name_en FROM product_catalog ORDER BY display_order")).all()
    assert ("3037", "3037.HK", "CSOP Hang Seng Index ETF") in products
    assert ("3535", "3535.HK", "CSOP Nomura FTSE HK-Japan Equity Cash Flow ETF") in products
    command.check(config)
    command.downgrade(config, "base")
    assert set(inspect(engine).get_table_names()) == {"alembic_version"}
