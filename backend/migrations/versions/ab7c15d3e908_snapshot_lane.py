"""snapshot and report distribution lane

Splits "where the data came from" (``source_policy``) from "may this be distributed" (``lane``).
Everything that exists when this runs was produced before the split, so it is backfilled from the
policy that produced it: GOLDEN_FIXTURE rows are transcribed report data and become TESTING;
everything else keeps PRODUCTION.

Revision ID: ab7c15d3e908
Revises: fa13c7d9e204
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "ab7c15d3e908"
down_revision: Union[str, Sequence[str], None] = "fa13c7d9e204"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Added nullable, backfilled, then made NOT NULL: an existing row has no lane to state, and a
    # server_default would let a future insert stay silent about one.
    with op.batch_alter_table("data_snapshots") as batch:
        batch.add_column(sa.Column("lane", sa.String(16), nullable=True))
    with op.batch_alter_table("reports") as batch:
        batch.add_column(sa.Column("lane", sa.String(16), nullable=True))
    op.execute(sa.text("""
        UPDATE data_snapshots
        SET lane = CASE WHEN source_policy = 'GOLDEN_FIXTURE' THEN 'TESTING' ELSE 'PRODUCTION' END
    """))
    op.execute(sa.text("""
        UPDATE reports
        SET lane = COALESCE(
            (SELECT s.lane FROM data_snapshots s WHERE s.id = reports.active_snapshot_id),
            'PRODUCTION'
        )
    """))
    with op.batch_alter_table("data_snapshots") as batch:
        batch.alter_column("lane", existing_type=sa.String(16), nullable=False)
    with op.batch_alter_table("reports") as batch:
        batch.alter_column("lane", existing_type=sa.String(16), nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("reports") as batch:
        batch.drop_column("lane")
    with op.batch_alter_table("data_snapshots") as batch:
        batch.drop_column("lane")
