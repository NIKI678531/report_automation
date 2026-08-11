"""logical dataset upload slots

Revision ID: f8c2d4a6b901
Revises: e27a9c1b5d08
"""
from datetime import datetime, timezone
from typing import Sequence, Union
from uuid import uuid4

from alembic import op
import sqlalchemy as sa


revision: str = "f8c2d4a6b901"
down_revision: Union[str, Sequence[str], None] = "e27a9c1b5d08"
branch_labels = None
depends_on = None


PROFILE_IDS = (
    "standard_constituent_returns_csv",
    "standard_total_return_series_csv",
    "standard_fund_kpi_daily_csv",
    "standard_trading_calendar_csv",
    "standard_index_events_csv",
)


def upgrade() -> None:
    profiles = sa.table(
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
    op.execute(
        sa.update(profiles)
        .where(profiles.c.profile_id.in_(("bloomberg_gics_reference", "approved_sector_overrides")))
        .values(status="DRAFT")
    )
    now = datetime.now(timezone.utc)
    op.bulk_insert(profiles, [
        {
            "id": str(uuid4()), "profile_id": "standard_constituent_returns_csv",
            "dataset_type": "constituent_returns", "source_family": "STANDARD_CSV",
            "selector": {"extensions": [".csv"], "required_fields": ["security_code", "period_end", "period_start_1m", "return_1m", "period_start_3m", "return_3m", "period_start_6m", "return_6m", "period_start_ytd", "return_ytd", "source"]},
            "field_map": {field: {"aliases": [field]} for field in ("security_code", "name_en", "period_end", "period_start_1m", "return_1m", "period_start_3m", "return_3m", "period_start_6m", "return_6m", "period_start_ytd", "return_ytd", "source")},
            "unit_map": {"returns": "PERCENT"}, "transforms": {"security_code": "normalize_security_code"},
            "semantic_metadata": {"series_type": "TOTAL_RETURN", "period_boundaries": "explicit"},
            "version": 1, "status": "APPROVED", "approved_by": "migration", "created_at": now,
        },
        {
            "id": str(uuid4()), "profile_id": "standard_total_return_series_csv",
            "dataset_type": "total_return_series", "source_family": "STANDARD_CSV",
            "selector": {"extensions": [".csv"], "required_fields": ["instrument_role", "instrument_code", "trade_date", "total_return_value", "series_type", "currency", "source"]},
            "field_map": {field: {"aliases": [field]} for field in ("instrument_role", "instrument_code", "trade_date", "total_return_value", "series_type", "currency", "source")},
            "unit_map": {}, "transforms": {}, "semantic_metadata": {"series_type": "TOTAL_RETURN"},
            "version": 1, "status": "APPROVED", "approved_by": "migration", "created_at": now,
        },
        {
            "id": str(uuid4()), "profile_id": "standard_fund_kpi_daily_csv",
            "dataset_type": "fund_kpi_daily", "source_family": "STANDARD_CSV",
            "selector": {"extensions": [".csv"], "required_fields": ["metric_code", "metric_date", "value", "unit", "currency", "source"]},
            "field_map": {field: {"aliases": [field]} for field in ("metric_code", "metric_date", "value", "unit", "currency", "source")},
            "unit_map": {}, "transforms": {}, "semantic_metadata": {"amount_unit_source": "explicit"},
            "version": 1, "status": "APPROVED", "approved_by": "migration", "created_at": now,
        },
        {
            "id": str(uuid4()), "profile_id": "standard_trading_calendar_csv",
            "dataset_type": "trading_calendar", "source_family": "STANDARD_CSV",
            "selector": {"extensions": [".csv"], "required_fields": ["market", "date", "is_trading_day", "source"]},
            "field_map": {field: {"aliases": [field]} for field in ("market", "date", "is_trading_day", "source")},
            "unit_map": {}, "transforms": {}, "semantic_metadata": {},
            "version": 1, "status": "APPROVED", "approved_by": "migration", "created_at": now,
        },
        {
            "id": str(uuid4()), "profile_id": "standard_index_events_csv",
            "dataset_type": "index_events", "source_family": "STANDARD_CSV",
            "selector": {"extensions": [".csv"], "required_fields": ["index_code", "event_type", "effective_date", "source"]},
            "field_map": {field: {"aliases": [field]} for field in ("index_code", "event_type", "announcement_date", "effective_date", "source")},
            "unit_map": {}, "transforms": {}, "semantic_metadata": {},
            "version": 1, "status": "APPROVED", "approved_by": "migration", "created_at": now,
        },
    ])


def downgrade() -> None:
    profiles = sa.table(
        "mapping_profiles",
        sa.column("profile_id", sa.String),
        sa.column("status", sa.String),
    )
    op.execute(sa.delete(profiles).where(profiles.c.profile_id.in_(PROFILE_IDS)))
    op.execute(
        sa.update(profiles)
        .where(profiles.c.profile_id.in_(("bloomberg_gics_reference", "approved_sector_overrides")))
        .values(status="APPROVED")
    )
