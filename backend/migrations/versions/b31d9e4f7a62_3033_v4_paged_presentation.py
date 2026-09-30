"""3033 v4 paged presentation

Revision ID: b31d9e4f7a62
Revises: a19c7e3d5b82
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b31d9e4f7a62"
down_revision: Union[str, Sequence[str], None] = "a19c7e3d5b82"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(
        "UPDATE product_catalog SET template_version = '3033-v4', "
        "design_token_version = '3033-v4' "
        "WHERE product_code = '3033' AND template_version = '3033-v3' "
        "AND design_token_version = '3033-v3'"
    ))


def downgrade() -> None:
    op.execute(sa.text(
        "UPDATE product_catalog SET template_version = '3033-v3', "
        "design_token_version = '3033-v3' "
        "WHERE product_code = '3033' AND template_version = '3033-v4' "
        "AND design_token_version = '3033-v4'"
    ))
