"""Limit the active product scope to 3033 and seed its approved HSICS industries.

Revision ID: b7d8e9f0a123
Revises: c91e2f7a4b60
"""

from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
import json
from uuid import uuid4

from alembic import op
import sqlalchemy as sa


revision: str = "b7d8e9f0a123"
down_revision: str | None = "c91e2f7a4b60"
branch_labels = None
depends_on = None


VERSION = "HSICS-3033-2026.1"
SOURCE = "3033_BUSINESS_MAPPING_20260813"
INDUSTRIES = (
    ("10", "Industrials", "工業"),
    ("23", "Consumer Discretionary", "非必需性消費"),
    ("28", "Healthcare", "醫療保健"),
    ("50", "Financials", "金融"),
    ("70", "Information Technology", "資訊科技"),
)


def _industry_rows() -> list[dict]:
    now = datetime.now(timezone.utc)
    rows = []
    for code, name_en, name_zh_hant in INDUSTRIES:
        canonical = {
            "taxonomy": "HSICS",
            "version": VERSION,
            "level": "INDUSTRY",
            "code": code,
            "parent_code": None,
            "name_en": name_en,
            "name_zh_hant": name_zh_hant,
            "valid_from": date(2020, 8, 28),
            "valid_to": None,
            "source": SOURCE,
            "source_record_key": f"INDUSTRY:{code}",
        }
        digest_value = {
            key: value.isoformat() if isinstance(value, date) else value
            for key, value in canonical.items()
        }
        rows.append({
            "id": str(uuid4()),
            **canonical,
            "checksum": hashlib.sha256(
                json.dumps(digest_value, ensure_ascii=False, sort_keys=True).encode()
            ).hexdigest(),
            "created_at": now,
        })
    return rows


def upgrade() -> None:
    # The screenshot-derived expansion was provisional. Keep its rows for audit/rollback but make
    # them unavailable to report creation; 3033 is the only active product in this release.
    op.execute(sa.text(
        "UPDATE product_catalog SET is_active = false "
        "WHERE product_code <> '3033' AND source = 'CSOP_SCREENSHOT_202608'"
    ))

    bind = op.get_bind()
    industry_count = bind.execute(sa.text("SELECT COUNT(*) FROM industry_master")).scalar_one()
    if industry_count == 0:
        industry_master = sa.table(
            "industry_master",
            sa.column("id", sa.String),
            sa.column("taxonomy", sa.String),
            sa.column("version", sa.String),
            sa.column("level", sa.String),
            sa.column("code", sa.String),
            sa.column("parent_code", sa.String),
            sa.column("name_en", sa.String),
            sa.column("name_zh_hant", sa.String),
            sa.column("valid_from", sa.Date),
            sa.column("valid_to", sa.Date),
            sa.column("source", sa.String),
            sa.column("source_record_key", sa.String),
            sa.column("checksum", sa.String),
            sa.column("created_at", sa.DateTime(timezone=True)),
        )
        op.bulk_insert(industry_master, _industry_rows())


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM industry_master WHERE source = :source").bindparams(source=SOURCE))
    op.execute(sa.text(
        "UPDATE product_catalog SET is_active = true "
        "WHERE source = 'CSOP_SCREENSHOT_202608'"
    ))
