"""product automatic data bindings

Revision ID: fa13c7d9e204
Revises: f8c2d4a6b901
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "fa13c7d9e204"
down_revision: Union[str, Sequence[str], None] = "f8c2d4a6b901"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("product_catalog") as batch:
        batch.add_column(sa.Column("fund_total_return_instrument_code", sa.String(32), nullable=True))
        batch.add_column(sa.Column("fund_kpi_product_code", sa.String(32), nullable=True))
        batch.add_column(sa.Column("trading_calendar_code", sa.String(32), nullable=True))
    op.execute(sa.text("""
        UPDATE product_catalog
        SET fund_total_return_instrument_code = ticker,
            fund_kpi_product_code = product_code,
            trading_calendar_code = 'HK'
    """))


def downgrade() -> None:
    with op.batch_alter_table("product_catalog") as batch:
        batch.drop_column("trading_calendar_code")
        batch.drop_column("fund_kpi_product_code")
        batch.drop_column("fund_total_return_instrument_code")