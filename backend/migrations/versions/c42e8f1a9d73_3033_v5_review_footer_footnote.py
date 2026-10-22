"""3033 v5 Review footer footnote

Revision ID: c42e8f1a9d73
Revises: b31d9e4f7a62
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c42e8f1a9d73"
down_revision: Union[str, Sequence[str], None] = "b31d9e4f7a62"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(
        "UPDATE product_catalog SET template_version = '3033-v5', "
        "design_token_version = '3033-v5' "
        "WHERE product_code = '3033' AND template_version = '3033-v4' "
        "AND design_token_version = '3033-v4'"
    ))


def downgrade() -> None:
    op.execute(sa.text(
        "UPDATE product_catalog SET template_version = '3033-v4', "
        "design_token_version = '3033-v4' "
        "WHERE product_code = '3033' AND template_version = '3033-v5' "
        "AND design_token_version = '3033-v5'"
    ))
