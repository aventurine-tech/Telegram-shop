"""localized catalog: names and descriptions in en / ru / ro

Revision ID: d0e9f8a7b6c5
Revises: c9d8e7f6a5b4
Create Date: 2026-10-08 12:00:00.000000

Adds nullable display translations beside the canonical (main-language) ``name`` /
``description``, which stay the unique lookup keys. A NULL/blank translation falls back to the
canonical text, so existing rows keep working unchanged.

* categories.name_{en,ru,ro}
* goods.name_{en,ru,ro}, goods.description_{en,ru,ro}
* order_items.name_{en,ru,ro} — snapshot of the product's translated names at order time

On PostgreSQL the catalog search also gets trigram GIN indexes on the new goods columns
(same guarded style as f2a3b4c5d6e7) so ``ILIKE`` over all languages stays indexed.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = 'd0e9f8a7b6c5'
down_revision: Union[str, None] = 'c9d8e7f6a5b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LANGS = ('en', 'ru', 'ro')
# table -> [(column prefix, type)]
COLUMNS = {
    'categories': [('name', sa.String(100))],
    'goods': [('name', sa.String(100)), ('description', sa.Text())],
    'order_items': [('name', sa.String(100))],
}
TRGM_INDEXES = {
    f'ix_goods_{field}_{lang}_trgm': f'{field}_{lang}'
    for field in ('name', 'description') for lang in LANGS
}


def _has_trgm(bind) -> bool:
    return bool(bind.exec_driver_sql("SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm'").scalar())


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    for table, fields in COLUMNS.items():
        existing = {c['name'] for c in inspector.get_columns(table)}
        for prefix, coltype in fields:
            for lang in LANGS:
                name = f'{prefix}_{lang}'
                if name not in existing:
                    op.add_column(table, sa.Column(name, coltype, nullable=True))

    if bind.dialect.name == 'postgresql' and _has_trgm(bind):
        present = {i['name'] for i in inspect(bind).get_indexes('goods')}
        for index, column in TRGM_INDEXES.items():
            if index not in present:
                op.execute(f"CREATE INDEX {index} ON goods USING gin ({column} gin_trgm_ops)")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == 'postgresql':
        for index in TRGM_INDEXES:
            op.execute(f"DROP INDEX IF EXISTS {index}")
    inspector = inspect(bind)
    for table, fields in COLUMNS.items():
        existing = {c['name'] for c in inspector.get_columns(table)}
        for prefix, _ in fields:
            for lang in LANGS:
                name = f'{prefix}_{lang}'
                if name in existing:
                    op.drop_column(table, name)
