"""index news article identity on a hash of its URL

A unique index on ``news_items.source_url`` cannot exist on MySQL: VARCHAR(1000) with utf8mb4 is
4000 bytes and InnoDB's index key limit is 3072. Uniqueness moves to ``source_url_hash``, a sha256
hex digest that indexes at a fixed 64 bytes on every supported engine while the full URL stays
stored for citation and display.

SQLite databases created before this revision keep an unnamed UNIQUE on ``source_url`` from the
original CREATE TABLE. It is left in place - SQLite cannot drop an unnamed constraint without
rebuilding the table, and it enforces exactly the same invariant as the new index.

Revision ID: d4e1f7a92c30
Revises: c8f0e1a2b345
Create Date: 2026-09-03
"""

from collections.abc import Sequence
import hashlib

from alembic import op
import sqlalchemy as sa


revision: str = "d4e1f7a92c30"
down_revision: str | None = "c8f0e1a2b345"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEWS_ITEMS = sa.table(
    "news_items",
    sa.column("id", sa.String),
    sa.column("source_url", sa.String),
    sa.column("source_url_hash", sa.String),
)


def upgrade() -> None:
    connection = op.get_bind()
    op.add_column("news_items", sa.Column("source_url_hash", sa.String(length=64), nullable=True))
    # Backfilled row by row rather than with a SQL hash function: MySQL spells it SHA2(x, 256)
    # and SQLite has no built-in equivalent, so Python is the only expression of the key that both
    # engines and the application agree on.
    for row in connection.execute(sa.select(_NEWS_ITEMS.c.id, _NEWS_ITEMS.c.source_url)):
        connection.execute(
            _NEWS_ITEMS.update()
            .where(_NEWS_ITEMS.c.id == row.id)
            .values(source_url_hash=hashlib.sha256((row.source_url or "").strip().encode("utf-8")).hexdigest())
        )
    with op.batch_alter_table("news_items") as batch:
        batch.alter_column("source_url_hash", existing_type=sa.String(length=64), nullable=False)
        batch.create_unique_constraint("uq_news_items_source_url_hash", ["source_url_hash"])


def downgrade() -> None:
    with op.batch_alter_table("news_items") as batch:
        batch.drop_constraint("uq_news_items_source_url_hash", type_="unique")
        batch.drop_column("source_url_hash")
