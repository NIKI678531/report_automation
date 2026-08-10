"""artifact canonical content manifest

Revision ID: e27a9c1b5d08
Revises: d16f8b0a4c97
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e27a9c1b5d08"
down_revision: Union[str, Sequence[str], None] = "d16f8b0a4c97"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("render_artifacts") as batch:
        batch.add_column(sa.Column("content_manifest", sa.JSON(), nullable=True))
    op.execute(sa.text("UPDATE render_artifacts SET content_manifest = '{}' WHERE content_manifest IS NULL"))
    with op.batch_alter_table("render_artifacts") as batch:
        batch.alter_column("content_manifest", existing_type=sa.JSON(), nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("render_artifacts") as batch:
        batch.drop_column("content_manifest")