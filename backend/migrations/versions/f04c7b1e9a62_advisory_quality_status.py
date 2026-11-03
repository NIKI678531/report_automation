"""Remove the QA_BLOCKED report lifecycle state

Revision ID: f04c7b1e9a62
Revises: c42e8f1a9d73
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f04c7b1e9a62"
down_revision: Union[str, Sequence[str], None] = "c42e8f1a9d73"
branch_labels = None
depends_on = None


OLD = sa.Enum(
    "DRAFT", "DATA_READY", "EDITING", "QA_BLOCKED", "READY_TO_FINALIZE",
    "REVIEW", "FINALIZED", "ARCHIVED", name="reportstatus",
)
NEW = sa.Enum(
    "DRAFT", "DATA_READY", "EDITING", "READY_TO_FINALIZE",
    "REVIEW", "FINALIZED", "ARCHIVED", name="reportstatus",
)


def upgrade() -> None:
    op.execute(sa.text("UPDATE reports SET status = 'EDITING' WHERE status = 'QA_BLOCKED'"))
    with op.batch_alter_table("reports") as batch:
        batch.alter_column("status", existing_type=OLD, type_=NEW, existing_nullable=False)


def downgrade() -> None:
    # The old value cannot be reconstructed: quality findings were advisory after this revision.
    with op.batch_alter_table("reports") as batch:
        batch.alter_column("status", existing_type=NEW, type_=OLD, existing_nullable=False)
