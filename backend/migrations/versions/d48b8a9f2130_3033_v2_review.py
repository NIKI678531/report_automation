"""3033 v2 review template

Revision ID: d48b8a9f2130
Revises: c216f31d8a42
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "d48b8a9f2130"
down_revision: Union[str, Sequence[str], None] = "c216f31d8a42"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(
        "UPDATE product_catalog SET template_version = '3033-v2', design_token_version = '3033-v2' "
        "WHERE product_code = '3033' AND template_version = '3033-v1'"
    ))


def downgrade() -> None:
    op.execute(sa.text(
        "UPDATE product_catalog SET template_version = '3033-v1', design_token_version = '3033-v1' "
        "WHERE product_code = '3033' AND template_version = '3033-v2'"
    ))