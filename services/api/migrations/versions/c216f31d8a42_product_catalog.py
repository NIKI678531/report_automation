"""product catalog

Revision ID: c216f31d8a42
Revises: b905c1f201b2
"""
from datetime import date, datetime, timezone
from typing import Sequence, Union
from uuid import uuid4

from alembic import op
import sqlalchemy as sa

revision: str = "c216f31d8a42"
down_revision: Union[str, Sequence[str], None] = "b905c1f201b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    product_catalog = op.create_table(
        "product_catalog",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("product_code", sa.String(32), nullable=False),
        sa.Column("ticker", sa.String(32), nullable=False),
        sa.Column("name_en", sa.String(255), nullable=False),
        sa.Column("name_zh_hant", sa.String(255), nullable=True),
        sa.Column("benchmark_code", sa.String(32), nullable=False),
        sa.Column("benchmark_name", sa.String(255), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column("template_version", sa.String(32), nullable=False),
        sa.Column("design_token_version", sa.String(32), nullable=False),
        sa.Column("expected_constituent_count", sa.Integer(), nullable=True),
        sa.Column("formula_profile", sa.String(64), nullable=False),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("product_code", "valid_from", name="uq_product_catalog_version"),
    )
    op.create_index("ix_product_catalog_product_code", "product_catalog", ["product_code"])
    op.create_index("ix_product_catalog_ticker", "product_catalog", ["ticker"])

    now = datetime.now(timezone.utc)
    op.bulk_insert(product_catalog, [{
        "id": str(uuid4()),
        "product_code": "3033",
        "ticker": "3033.HK",
        "name_en": "CSOP Hang Seng TECH Index ETF",
        "name_zh_hant": "南方東英恒生科技指數ETF",
        "benchmark_code": "HSTECH",
        "benchmark_name": "Hang Seng TECH Index",
        "currency": "HKD",
        "timezone": "Asia/Hong_Kong",
        "valid_from": date(2020, 8, 28),
        "valid_to": None,
        "is_active": True,
        "display_order": 10,
        "template_version": "3033-v1",
        "design_token_version": "3033-v1",
        "expected_constituent_count": 30,
        "formula_profile": "hstech-2026.1",
        "source": "PROJECT_BASELINE",
        "source_updated_at": now,
        "created_at": now,
        "updated_at": now,
    }])


def downgrade() -> None:
    op.drop_index("ix_product_catalog_ticker", table_name="product_catalog")
    op.drop_index("ix_product_catalog_product_code", table_name="product_catalog")
    op.drop_table("product_catalog")