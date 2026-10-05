"""product options

Revision ID: a7c3e5f1b2d4
Revises: e1f0a9b8c7d6
Create Date: 2026-10-10 12:00:00.000000

``goods.variant_of`` / ``goods.variant_label`` — a product may have weight options, each its own
row grouped under a head product. NULL = head or standalone, so every existing product stays as is.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = 'a7c3e5f1b2d4'
down_revision: Union[str, None] = 'e1f0a9b8c7d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    if 'variant_of' in {c['name'] for c in inspector.get_columns('goods')}:
        return
    with op.batch_alter_table('goods') as batch:
        batch.add_column(sa.Column('variant_of', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('variant_label', sa.String(length=32), nullable=True))
        batch.create_foreign_key('fk_goods_variant_of', 'goods', ['variant_of'], ['id'],
                                 ondelete='CASCADE')
        batch.create_index('ix_goods_variant_of', ['variant_of'])


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    if 'variant_of' not in {c['name'] for c in inspector.get_columns('goods')}:
        return
    with op.batch_alter_table('goods') as batch:
        batch.drop_index('ix_goods_variant_of')
        batch.drop_constraint('fk_goods_variant_of', type_='foreignkey')
        batch.drop_column('variant_label')
        batch.drop_column('variant_of')
