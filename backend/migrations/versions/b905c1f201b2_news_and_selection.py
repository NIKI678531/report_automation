"""news candidates and report selections

Revision ID: b905c1f201b2
Revises: a814ab1a018d
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "b905c1f201b2"
down_revision: Union[str, Sequence[str], None] = "a814ab1a018d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "news_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source_name", sa.String(120), nullable=False),
        sa.Column("source_url", sa.String(1000), nullable=False, unique=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("title", sa.String(1000), nullable=False),
        sa.Column("summary", sa.String(5000), nullable=False),
        sa.Column("security_code", sa.String(32), nullable=True),
        sa.Column("ticker", sa.String(32), nullable=True),
        sa.Column("importance", sa.String(20), nullable=False),
        sa.Column("match_confidence", sa.Integer(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_news_items_security_code", "news_items", ["security_code"])
    op.create_table(
        "report_news_selections",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("report_id", sa.String(36), sa.ForeignKey("reports.id"), nullable=False),
        sa.Column("news_item_id", sa.String(36), sa.ForeignKey("news_items.id"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("title_override", sa.String(1000), nullable=True),
        sa.Column("summary_override", sa.String(5000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("report_id", "news_item_id", name="uq_report_news_item"),
    )
    op.create_index("ix_report_news_selections_report_id", "report_news_selections", ["report_id"])
    op.create_index("ix_report_news_selections_news_item_id", "report_news_selections", ["news_item_id"])


def downgrade() -> None:
    op.drop_index("ix_report_news_selections_news_item_id", table_name="report_news_selections")
    op.drop_index("ix_report_news_selections_report_id", table_name="report_news_selections")
    op.drop_table("report_news_selections")
    op.drop_index("ix_news_items_security_code", table_name="news_items")
    op.drop_table("news_items")
