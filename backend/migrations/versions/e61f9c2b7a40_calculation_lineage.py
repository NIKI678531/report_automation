"""calculation lineage records

Revision ID: e61f9c2b7a40
Revises: f3b8c4d2a6e1
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e61f9c2b7a40"
down_revision: Union[str, Sequence[str], None] = "f3b8c4d2a6e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "snapshot_datasets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("snapshot_id", sa.String(36), sa.ForeignKey("data_snapshots.id"), nullable=False),
        sa.Column("dataset_type", sa.String(64), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("source_object", sa.String(1000), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("coverage", sa.Numeric(38, 18), nullable=True),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("parser_version", sa.String(64), nullable=True),
        sa.Column("mapping_version", sa.String(64), nullable=False),
        sa.Column("validation_results", sa.JSON(), nullable=False),
        sa.Column("lineage", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("snapshot_id", "dataset_type", name="uq_snapshot_dataset_type"),
    )
    op.create_index("ix_snapshot_datasets_snapshot_id", "snapshot_datasets", ["snapshot_id"])

    op.create_table(
        "metric_values",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("snapshot_id", sa.String(36), sa.ForeignKey("data_snapshots.id"), nullable=False),
        sa.Column("metric_code", sa.String(100), nullable=False),
        sa.Column("dimension_key", sa.String(255), nullable=False),
        sa.Column("value", sa.Numeric(38, 18), nullable=True),
        sa.Column("raw_value", sa.String(500), nullable=False),
        sa.Column("unit", sa.String(32), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=True),
        sa.Column("period_end", sa.Date(), nullable=True),
        sa.Column("formula_version", sa.String(64), nullable=False),
        sa.Column("lineage", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("snapshot_id", "metric_code", "dimension_key", "formula_version", name="uq_metric_value_version"),
    )
    op.create_index("ix_metric_values_snapshot_id", "metric_values", ["snapshot_id"])
    op.create_index("ix_metric_values_metric_code", "metric_values", ["metric_code"])

    op.create_table(
        "module_snapshots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("snapshot_id", sa.String(36), sa.ForeignKey("data_snapshots.id"), nullable=False),
        sa.Column("module_code", sa.String(64), nullable=False),
        sa.Column("formula_version", sa.String(64), nullable=False),
        sa.Column("template_version", sa.String(64), nullable=False),
        sa.Column("source_dataset_ids", sa.JSON(), nullable=False),
        sa.Column("metric_value_ids", sa.JSON(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("display_format", sa.JSON(), nullable=False),
        sa.Column("footnote_bindings", sa.JSON(), nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("input_checksum", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("snapshot_id", "module_code", "formula_version", "template_version", name="uq_module_snapshot_version"),
    )
    op.create_index("ix_module_snapshots_snapshot_id", "module_snapshots", ["snapshot_id"])
    op.create_index("ix_module_snapshots_module_code", "module_snapshots", ["module_code"])

    op.create_table(
        "quality_check_results",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("snapshot_id", sa.String(36), sa.ForeignKey("data_snapshots.id"), nullable=False),
        sa.Column("source_dataset_id", sa.String(36), sa.ForeignKey("snapshot_datasets.id"), nullable=True),
        sa.Column("result_key", sa.String(255), nullable=False),
        sa.Column("check_id", sa.String(32), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("entity_id", sa.String(100), nullable=True),
        sa.Column("actual", sa.JSON(), nullable=True),
        sa.Column("threshold", sa.JSON(), nullable=True),
        sa.Column("fix_hint", sa.String(1000), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("snapshot_id", "result_key", name="uq_snapshot_quality_result"),
    )
    op.create_index("ix_quality_check_results_snapshot_id", "quality_check_results", ["snapshot_id"])
    op.create_index("ix_quality_check_results_check_id", "quality_check_results", ["check_id"])


def downgrade() -> None:
    op.drop_index("ix_quality_check_results_check_id", table_name="quality_check_results")
    op.drop_index("ix_quality_check_results_snapshot_id", table_name="quality_check_results")
    op.drop_table("quality_check_results")
    op.drop_index("ix_module_snapshots_module_code", table_name="module_snapshots")
    op.drop_index("ix_module_snapshots_snapshot_id", table_name="module_snapshots")
    op.drop_table("module_snapshots")
    op.drop_index("ix_metric_values_metric_code", table_name="metric_values")
    op.drop_index("ix_metric_values_snapshot_id", table_name="metric_values")
    op.drop_table("metric_values")
    op.drop_index("ix_snapshot_datasets_snapshot_id", table_name="snapshot_datasets")
    op.drop_table("snapshot_datasets")