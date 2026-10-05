"""subcategories

Revision ID: e1f0a9b8c7d6
Revises: d0e9f8a7b6c5
Create Date: 2026-10-09 12:00:00.000000

``categories.parent_id`` — a category may sit under a top-level parent (two levels at most; the
rule that a parent holds no products is enforced in code). NULL = top-level, so every existing
category stays as it is.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = 'e1f0a9b8c7d6'
down_revision: Union[str, None] = 'd0e9f8a7b6c5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    if 'parent_id' in {c['name'] for c in inspector.get_columns('categories')}:
        return
    with op.batch_alter_table('categories') as batch:
        batch.add_column(sa.Column('parent_id', sa.Integer(), nullable=True))
        batch.create_foreign_key('fk_categories_parent_id', 'categories', ['parent_id'], ['id'],
                                 ondelete='RESTRICT')
        batch.create_index('ix_categories_parent_id', ['parent_id'])


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    if 'parent_id' not in {c['name'] for c in inspector.get_columns('categories')}:
        return
    with op.batch_alter_table('categories') as batch:
        batch.drop_index('ix_categories_parent_id')
        batch.drop_constraint('fk_categories_parent_id', type_='foreignkey')
        batch.drop_column('parent_id')
