"""report news candidate lineage and idempotent fetch runs

Revision ID: a83c5e7d1f64
Revises: f72a1d4e9b53
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a83c5e7d1f64"
down_revision: Union[str, Sequence[str], None] = "f72a1d4e9b53"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "report_news_candidates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("report_id", sa.String(36), sa.ForeignKey("reports.id"), nullable=False),
        sa.Column("news_item_id", sa.String(36), sa.ForeignKey("news_items.id"), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("match_status", sa.String(20), nullable=False),
        sa.Column("match_evidence", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("report_id", "news_item_id", name="uq_report_news_candidate"),
    )
    op.create_index("ix_report_news_candidates_report_id", "report_news_candidates", ["report_id"])
    op.create_index("ix_report_news_candidates_news_item_id", "report_news_candidates", ["news_item_id"])

    op.create_table(
        "news_fetch_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("report_id", sa.String(36), sa.ForeignKey("reports.id"), nullable=False),
        sa.Column("snapshot_id", sa.String(36), sa.ForeignKey("data_snapshots.id"), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("scope", sa.String(20), nullable=False),
        sa.Column("from_date", sa.Date(), nullable=False),
        sa.Column("to_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("fetched_count", sa.Integer(), nullable=False),
        sa.Column("matched_count", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("report_id", "snapshot_id", "provider", "scope", "from_date", "to_date", name="uq_news_fetch_window"),
    )
    op.create_index("ix_news_fetch_runs_report_id", "news_fetch_runs", ["report_id"])
    op.create_index("ix_news_fetch_runs_snapshot_id", "news_fetch_runs", ["snapshot_id"])


def downgrade() -> None:
    op.drop_index("ix_news_fetch_runs_snapshot_id", table_name="news_fetch_runs")
    op.drop_index("ix_news_fetch_runs_report_id", table_name="news_fetch_runs")
    op.drop_table("news_fetch_runs")
    op.drop_index("ix_report_news_candidates_news_item_id", table_name="report_news_candidates")
    op.drop_index("ix_report_news_candidates_report_id", table_name="report_news_candidates")
    op.drop_table("report_news_candidates")