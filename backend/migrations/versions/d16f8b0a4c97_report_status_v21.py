"""V2.1 report lifecycle states

Revision ID: d16f8b0a4c97
Revises: c05e7a9f3b86
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d16f8b0a4c97"
down_revision: Union[str, Sequence[str], None] = "c05e7a9f3b86"
branch_labels = None
depends_on = None


OLD = sa.Enum("DRAFT", "REVIEW", "FINALIZED", name="reportstatus")
NEW = sa.Enum(
    "DRAFT", "DATA_READY", "EDITING", "QA_BLOCKED", "READY_TO_FINALIZE",
    "REVIEW", "FINALIZED", "ARCHIVED", name="reportstatus",
)


def upgrade() -> None:
    with op.batch_alter_table("reports") as batch:
        batch.alter_column("status", existing_type=OLD, type_=NEW, existing_nullable=False)


def downgrade() -> None:
    op.execute(sa.text("UPDATE reports SET status = 'REVIEW' WHERE status IN ('DATA_READY', 'EDITING', 'QA_BLOCKED', 'READY_TO_FINALIZE')"))
    op.execute(sa.text("UPDATE reports SET status = 'FINALIZED' WHERE status = 'ARCHIVED'"))
    with op.batch_alter_table("reports") as batch:
        batch.alter_column("status", existing_type=NEW, type_=OLD, existing_nullable=False)