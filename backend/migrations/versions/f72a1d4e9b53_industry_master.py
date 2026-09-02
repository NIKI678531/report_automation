"""effective-dated industry master

Revision ID: f72a1d4e9b53
Revises: e61f9c2b7a40
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f72a1d4e9b53"
down_revision: Union[str, Sequence[str], None] = "e61f9c2b7a40"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "industry_master",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("taxonomy", sa.String(32), nullable=False),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("level", sa.String(16), nullable=False),
        sa.Column("code", sa.String(6), nullable=False),
        sa.Column("parent_code", sa.String(4), nullable=True),
        sa.Column("name_en", sa.String(255), nullable=False),
        sa.Column("name_zh_hant", sa.String(255), nullable=True),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("source", sa.String(255), nullable=False),
        sa.Column("source_record_key", sa.String(255), nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("taxonomy", "version", "level", "code", name="uq_industry_master_code"),
    )
    op.create_index("ix_industry_master_taxonomy", "industry_master", ["taxonomy"])
    op.create_index("ix_industry_master_version", "industry_master", ["version"])


def downgrade() -> None:
    op.drop_index("ix_industry_master_version", table_name="industry_master")
    op.drop_index("ix_industry_master_taxonomy", table_name="industry_master")
    op.drop_table("industry_master")