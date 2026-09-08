"""Persist version-bound editorial translation jobs."""

from alembic import op
import sqlalchemy as sa

revision = "e91c2d3f4a50"
down_revision = "d4e1f7a92c30"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "translation_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source_report_id", sa.String(36), sa.ForeignKey("reports.id"), nullable=False),
        sa.Column("target_report_id", sa.String(36), sa.ForeignKey("reports.id"), nullable=False),
        sa.Column("source_document_version", sa.Integer(), nullable=False),
        sa.Column("target_document_version", sa.Integer(), nullable=False),
        sa.Column("actor", sa.String(120), nullable=False),
        sa.Column("request_id", sa.String(100), nullable=False),
        sa.Column("idempotency_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("model", sa.String(255), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("result_document_version", sa.Integer(), nullable=True),
        sa.Column("preserved_fields", sa.JSON(), nullable=False),
        sa.Column("error", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_translation_jobs_source_report_id", "translation_jobs", ["source_report_id"])
    op.create_index("ix_translation_jobs_target_report_id", "translation_jobs", ["target_report_id"])


def downgrade():
    op.drop_table("translation_jobs")