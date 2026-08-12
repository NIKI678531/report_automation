"""Add atomic multi-file import batches.

Revision ID: c91e2f7a4b60
Revises: ab7c15d3e908
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "c91e2f7a4b60"
down_revision: str | None = "ab7c15d3e908"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "import_batches",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("report_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("validation_results", sa.JSON(), nullable=False),
        sa.Column("composition", sa.JSON(), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("applied_snapshot_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["report_id"], ["reports.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_import_batches_report_id"), "import_batches", ["report_id"], unique=False)
    with op.batch_alter_table("data_imports") as batch_op:
        batch_op.add_column(sa.Column("batch_id", sa.String(length=36), nullable=True))
        batch_op.create_foreign_key("fk_data_imports_batch_id", "import_batches", ["batch_id"], ["id"])
        batch_op.create_index("ix_data_imports_batch_id", ["batch_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("data_imports") as batch_op:
        batch_op.drop_index("ix_data_imports_batch_id")
        batch_op.drop_constraint("fk_data_imports_batch_id", type_="foreignkey")
        batch_op.drop_column("batch_id")
    op.drop_index(op.f("ix_import_batches_report_id"), table_name="import_batches")
    op.drop_table("import_batches")
