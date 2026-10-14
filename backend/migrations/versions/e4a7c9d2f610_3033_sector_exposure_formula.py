"""3033 classified sector exposure formula

Revision ID: e4a7c9d2f610
Revises: b31d9e4f7a62
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e4a7c9d2f610"
down_revision: Union[str, Sequence[str], None] = "b31d9e4f7a62"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(
        "UPDATE product_catalog SET formula_profile = 'hstech-2026.2' "
        "WHERE product_code = '3033' AND formula_profile = 'hstech-2026.1'"
    ))


def downgrade() -> None:
    op.execute(sa.text(
        "UPDATE product_catalog SET formula_profile = 'hstech-2026.1' "
        "WHERE product_code = '3033' AND formula_profile = 'hstech-2026.2'"
    ))
