"""add simplified Chinese language variants and copy lineage

Revision ID: c8f0e1a2b345
Revises: b7d8e9f0a123
Create Date: 2026-08-24
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "c8f0e1a2b345"
down_revision: str | None = "b7d8e9f0a123"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("product_catalog") as batch:
        batch.add_column(sa.Column("name_zh_hans", sa.String(length=255), nullable=True))
    with op.batch_alter_table("industry_master") as batch:
        batch.add_column(sa.Column("name_zh_hans", sa.String(length=255), nullable=True))
    with op.batch_alter_table("reports") as batch:
        batch.add_column(sa.Column("translation_source_report_id", sa.String(length=36), nullable=True))
        batch.create_foreign_key(
            "fk_reports_translation_source_report_id_reports",
            "reports",
            ["translation_source_report_id"],
            ["id"],
        )
        batch.create_index(
            "ix_reports_translation_source_report_id",
            ["translation_source_report_id"],
            unique=False,
        )
        batch.create_unique_constraint(
            "uq_report_language_variant",
            ["translation_source_report_id", "language_mode"],
        )
    with op.batch_alter_table("data_snapshots") as batch:
        batch.add_column(sa.Column("source_snapshot_id", sa.String(length=36), nullable=True))
        batch.create_foreign_key(
            "fk_data_snapshots_source_snapshot_id_data_snapshots",
            "data_snapshots",
            ["source_snapshot_id"],
            ["id"],
        )
        batch.create_index("ix_data_snapshots_source_snapshot_id", ["source_snapshot_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("data_snapshots") as batch:
        batch.drop_index("ix_data_snapshots_source_snapshot_id")
        batch.drop_constraint("fk_data_snapshots_source_snapshot_id_data_snapshots", type_="foreignkey")
        batch.drop_column("source_snapshot_id")
    with op.batch_alter_table("reports") as batch:
        batch.drop_constraint("uq_report_language_variant", type_="unique")
        batch.drop_index("ix_reports_translation_source_report_id")
        batch.drop_constraint("fk_reports_translation_source_report_id_reports", type_="foreignkey")
        batch.drop_column("translation_source_report_id")
    with op.batch_alter_table("industry_master") as batch:
        batch.drop_column("name_zh_hans")
    with op.batch_alter_table("product_catalog") as batch:
        batch.drop_column("name_zh_hans")
