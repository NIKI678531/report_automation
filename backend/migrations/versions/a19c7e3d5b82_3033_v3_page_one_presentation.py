"""3033 v3 page-one presentation

Revision ID: a19c7e3d5b82
Revises: e91c2d3f4a50
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a19c7e3d5b82"
down_revision: Union[str, Sequence[str], None] = "e91c2d3f4a50"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(
        "UPDATE product_catalog SET template_version = '3033-v3', "
        "design_token_version = '3033-v3' "
        "WHERE product_code = '3033' AND template_version = '3033-v2' "
        "AND design_token_version = '3033-v2'"
    ))


def downgrade() -> None:
    op.execute(sa.text(
        "UPDATE product_catalog SET template_version = '3033-v2', "
        "design_token_version = '3033-v2' "
        "WHERE product_code = '3033' AND template_version = '3033-v3' "
        "AND design_token_version = '3033-v3'"
    ))

