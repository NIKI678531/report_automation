"""split constituent index and return benchmark roles

Revision ID: c05e7a9f3b86
Revises: b94d6f8e2a75
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c05e7a9f3b86"
down_revision: Union[str, Sequence[str], None] = "b94d6f8e2a75"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("product_catalog") as batch:
        batch.add_column(sa.Column("constituent_index_code", sa.String(32), nullable=True))
        batch.add_column(sa.Column("constituent_index_name", sa.String(255), nullable=True))
        batch.add_column(sa.Column("benchmark_instrument_code", sa.String(32), nullable=True))
        batch.add_column(sa.Column("benchmark_instrument_name", sa.String(255), nullable=True))
    op.execute(sa.text("""
        UPDATE product_catalog
        SET constituent_index_code = benchmark_code,
            constituent_index_name = benchmark_name,
            benchmark_instrument_code = CASE WHEN product_code = '3033' THEN 'HSTECHN' ELSE benchmark_code END,
            benchmark_instrument_name = CASE WHEN product_code = '3033' THEN 'HSTECHN Index' ELSE benchmark_name END
    """))
    with op.batch_alter_table("product_catalog") as batch:
        batch.alter_column("constituent_index_code", existing_type=sa.String(32), nullable=False)
        batch.alter_column("benchmark_instrument_code", existing_type=sa.String(32), nullable=False)

    with op.batch_alter_table("reports") as batch:
        batch.add_column(sa.Column("constituent_index_code", sa.String(32), nullable=True))
        batch.add_column(sa.Column("benchmark_instrument_code", sa.String(32), nullable=True))
    op.execute(sa.text("""
        UPDATE reports
        SET constituent_index_code = benchmark_code,
            benchmark_instrument_code = CASE WHEN product_code = '3033' THEN 'HSTECHN' ELSE benchmark_code END
    """))
    with op.batch_alter_table("reports") as batch:
        batch.alter_column("constituent_index_code", existing_type=sa.String(32), nullable=False)
        batch.alter_column("benchmark_instrument_code", existing_type=sa.String(32), nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("reports") as batch:
        batch.drop_column("benchmark_instrument_code")
        batch.drop_column("constituent_index_code")
    with op.batch_alter_table("product_catalog") as batch:
        batch.drop_column("benchmark_instrument_name")
        batch.drop_column("benchmark_instrument_code")
        batch.drop_column("constituent_index_name")
        batch.drop_column("constituent_index_code")