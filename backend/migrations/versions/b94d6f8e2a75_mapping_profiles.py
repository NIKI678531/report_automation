"""versioned mapping profiles

Revision ID: b94d6f8e2a75
Revises: a83c5e7d1f64
"""
from datetime import datetime, timezone
from typing import Sequence, Union
from uuid import uuid4

from alembic import op
import sqlalchemy as sa


revision: str = "b94d6f8e2a75"
down_revision: Union[str, Sequence[str], None] = "a83c5e7d1f64"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mapping_profiles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("profile_id", sa.String(100), nullable=False),
        sa.Column("dataset_type", sa.String(64), nullable=False),
        sa.Column("source_family", sa.String(100), nullable=False),
        sa.Column("selector", sa.JSON(), nullable=False),
        sa.Column("field_map", sa.JSON(), nullable=False),
        sa.Column("unit_map", sa.JSON(), nullable=False),
        sa.Column("transforms", sa.JSON(), nullable=False),
        sa.Column("semantic_metadata", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("approved_by", sa.String(120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("profile_id", "version", name="uq_mapping_profile_version"),
    )
    op.create_index("ix_mapping_profiles_profile_id", "mapping_profiles", ["profile_id"])
    op.create_index("ix_mapping_profiles_dataset_type", "mapping_profiles", ["dataset_type"])
    with op.batch_alter_table("data_imports") as batch:
        batch.add_column(sa.Column("mapping_profile_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("mapping_version", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_data_imports_mapping_profile", "mapping_profiles", ["mapping_profile_id"], ["id"])
        batch.create_index("ix_data_imports_mapping_profile_id", ["mapping_profile_id"])
    mapping_profiles = sa.table(
        "mapping_profiles",
        sa.column("id", sa.String),
        sa.column("profile_id", sa.String),
        sa.column("dataset_type", sa.String),
        sa.column("source_family", sa.String),
        sa.column("selector", sa.JSON),
        sa.column("field_map", sa.JSON),
        sa.column("unit_map", sa.JSON),
        sa.column("transforms", sa.JSON),
        sa.column("semantic_metadata", sa.JSON),
        sa.column("version", sa.Integer),
        sa.column("status", sa.String),
        sa.column("approved_by", sa.String),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    now = datetime.now(timezone.utc)
    op.bulk_insert(mapping_profiles, [
        {
            "id": str(uuid4()), "profile_id": "hsi_constituent_csv", "dataset_type": "index_constituents",
            "source_family": "HANG_SENG_INDEXES_EOD",
            "selector": {"extensions": [".csv"], "required_fields": ["security_code", "weight", "close_price"]},
            "field_map": {
                "security_code": {"aliases": ["Lcal Cde"]}, "name_en": {"aliases": ["Stk Name_E"]},
                "name_zh_hant": {"aliases": ["Stk Name_TC"]}, "close_price": {"aliases": ["Cls Price"]},
                "currency": {"aliases": ["Lcal Ccy"]}, "weight": {"aliases": ["Pct Idx Wgt"]},
                "as_of_date": {"aliases": ["Prod Dt"]}, "trade_date": {"aliases": ["Tradate"]},
                "source_industry_code": {"aliases": ["Industry"]}, "source_sector_code": {"aliases": ["Sector"]},
            },
            "unit_map": {"weight": "PERCENT"}, "transforms": {}, "semantic_metadata": {"taxonomy": "HSICS"},
            "version": 1, "status": "APPROVED", "approved_by": "migration", "created_at": now,
        },
        {
            "id": str(uuid4()), "profile_id": "bloomberg_constituent_returns", "dataset_type": "constituent_returns",
            "source_family": "BLOOMBERG_MONTHLY_WORKBOOK",
            "selector": {"extensions": [".xlsx", ".xlsm"], "required_fields": ["return_1m", "return_3m", "return_6m", "return_ytd"], "header_scan_rows": 20, "period_row_offset": -2, "period_end_column": 1},
            "field_map": {
                "security_code": {"confirmed_column": 13}, "name_en": {"confirmed_column": 14},
                "return_1m": {"aliases": ["1-month return (%)"]}, "return_3m": {"aliases": ["3-month return (%)"]},
                "return_6m": {"aliases": ["6-month return (%)"]}, "return_ytd": {"aliases": ["YTD return (%)"]},
            },
            "unit_map": {"returns": "PERCENT"}, "transforms": {"security_code": "normalize_security_code"},
            "semantic_metadata": {"series_type": "TOTAL_RETURN", "duplicate_group_policy": "FIRST_COMPLETE_GROUP"},
            "version": 1, "status": "APPROVED", "approved_by": "migration", "created_at": now,
        },
        {
            "id": str(uuid4()), "profile_id": "bloomberg_gics_reference", "dataset_type": "sector_mapping",
            "source_family": "BLOOMBERG_GICS_REFERENCE",
            "selector": {"extensions": [".xlsx", ".xlsm", ".csv"], "required_fields": ["security_code", "sector"], "header_scan_rows": 20},
            "field_map": {"security_code": {"aliases": ["Code"]}, "sector": {"aliases": ["GICS_SECTOR_NAME"]}},
            "unit_map": {}, "transforms": {"security_code": "normalize_security_code"},
            "semantic_metadata": {"taxonomy": "GICS", "reference_only": True},
            "version": 1, "status": "APPROVED", "approved_by": "migration", "created_at": now,
        },
        {
            "id": str(uuid4()), "profile_id": "approved_sector_overrides", "dataset_type": "sector_overrides",
            "source_family": "APPROVED_MANUAL_OVERRIDE",
            "selector": {"extensions": [".csv"], "required_fields": ["security_code", "sector", "reason", "source"]},
            "field_map": {
                "security_code": {"aliases": ["security_code"]}, "sector": {"aliases": ["sector"]},
                "reason": {"aliases": ["reason"]}, "source": {"aliases": ["source"]},
            },
            "unit_map": {}, "transforms": {"security_code": "normalize_security_code"},
            "semantic_metadata": {"reference_only": True},
            "version": 1, "status": "APPROVED", "approved_by": "migration", "created_at": now,
        },
    ])


def downgrade() -> None:
    with op.batch_alter_table("data_imports") as batch:
        batch.drop_index("ix_data_imports_mapping_profile_id")
        batch.drop_constraint("fk_data_imports_mapping_profile", type_="foreignkey")
        batch.drop_column("mapping_version")
        batch.drop_column("mapping_profile_id")
    op.drop_index("ix_mapping_profiles_dataset_type", table_name="mapping_profiles")
    op.drop_index("ix_mapping_profiles_profile_id", table_name="mapping_profiles")
    op.drop_table("mapping_profiles")