"""seed csop etf catalog

Revision ID: f3b8c4d2a6e1
Revises: d48b8a9f2130
"""
from datetime import date, datetime, timezone
from typing import Sequence, Union
from uuid import uuid4

from alembic import op
import sqlalchemy as sa

revision: str = "f3b8c4d2a6e1"
down_revision: Union[str, Sequence[str], None] = "d48b8a9f2130"
branch_labels = None
depends_on = None


PRODUCTS = [
    ("3037", "3037.HK", "CSOP Hang Seng Index ETF", "HSI", "Hang Seng Index", 20),
    ("3174", "3174.HK", "CSOP Hang Seng Biotech ETF", "HSBIO", "Hang Seng Biotech Index", 30),
    ("3432", "3432.HK", "CSOP MSCI HK China Connect Select ETF", "MSCIHKCC", "MSCI HK China Connect Select Index", 40),
    ("3441", "3441.HK", "CSOP FTSE East-West Equity Select ETF", "FTSEEWEQ", "FTSE East-West Equity Select Index", 50),
    ("3442", "3442.HK", "CSOP Hang Seng HK-US TECH ETF", "HSHKUSTECH", "Hang Seng HK-US TECH Index", 60),
    ("3443", "3443.HK", "CSOP FTSE Hong Kong Equity ETF", "FTSEHKEQ", "FTSE Hong Kong Equity Index", 70),
    ("3431", "3431.HK", "CSOP FTSE HK-Korea Tech+ Index ETF", "FTSEHKKRTECH", "FTSE HK-Korea Tech+ Index", 80),
    ("3469", "3469.HK", "CSOP Hang Seng Stock Connect High Dividend ETF", "HSSCHD", "Hang Seng Stock Connect High Dividend Index", 90),
    ("3473", "3473.HK", "CSOP FTSE Asia Tech Index ETF", "FTSEASIATECH", "FTSE Asia Tech Index", 100),
    ("3535", "3535.HK", "CSOP Nomura FTSE HK-Japan Equity Cash Flow ETF", "FTSEHKJPCF", "Nomura FTSE HK-Japan Equity Cash Flow Index", 110),
]


def upgrade() -> None:
    product_catalog = sa.table(
        "product_catalog",
        sa.column("id", sa.String),
        sa.column("product_code", sa.String),
        sa.column("ticker", sa.String),
        sa.column("name_en", sa.String),
        sa.column("name_zh_hant", sa.String),
        sa.column("benchmark_code", sa.String),
        sa.column("benchmark_name", sa.String),
        sa.column("currency", sa.String),
        sa.column("timezone", sa.String),
        sa.column("valid_from", sa.Date),
        sa.column("valid_to", sa.Date),
        sa.column("is_active", sa.Boolean),
        sa.column("display_order", sa.Integer),
        sa.column("template_version", sa.String),
        sa.column("design_token_version", sa.String),
        sa.column("expected_constituent_count", sa.Integer),
        sa.column("formula_profile", sa.String),
        sa.column("source", sa.String),
        sa.column("source_updated_at", sa.DateTime(timezone=True)),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    now = datetime.now(timezone.utc)
    op.bulk_insert(product_catalog, [
        {
            "id": str(uuid4()),
            "product_code": product_code,
            "ticker": ticker,
            "name_en": name_en,
            "name_zh_hant": None,
            "benchmark_code": benchmark_code,
            "benchmark_name": benchmark_name,
            "currency": "HKD",
            "timezone": "Asia/Hong_Kong",
            "valid_from": date(2026, 1, 1),
            "valid_to": None,
            "is_active": True,
            "display_order": display_order,
            "template_version": "3033-v2",
            "design_token_version": "3033-v2",
            "expected_constituent_count": None,
            "formula_profile": "total-return-v1",
            "source": "CSOP_SCREENSHOT_202608",
            "source_updated_at": now,
            "created_at": now,
            "updated_at": now,
        }
        for product_code, ticker, name_en, benchmark_code, benchmark_name, display_order in PRODUCTS
    ])


def downgrade() -> None:
    codes = ", ".join(f"'{product_code}'" for product_code, *_ in PRODUCTS)
    op.execute(sa.text(
        f"DELETE FROM product_catalog WHERE source = 'CSOP_SCREENSHOT_202608' AND product_code IN ({codes})"
    ))
