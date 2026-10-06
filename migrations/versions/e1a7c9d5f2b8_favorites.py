"""favorites

Revision ID: e1a7c9d5f2b8
Revises: d1f6b8c4e5a7
Create Date: 2026-10-15 12:00:00.000000

``favorites``: the products a customer starred (head products; PK = user + product, both cascade on delete).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = 'e1a7c9d5f2b8'
down_revision: Union[str, None] = 'd1f6b8c4e5a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    if 'favorites' not in inspector.get_table_names():
        op.create_table(
            'favorites',
            sa.Column('user_id', sa.BigInteger(), sa.ForeignKey('users.telegram_id', ondelete='CASCADE'),
                      primary_key=True),
            sa.Column('item_id', sa.Integer(), sa.ForeignKey('goods.id', ondelete='CASCADE'), primary_key=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index('ix_favorites_item_id', 'favorites', ['item_id'])


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    if 'favorites' in inspector.get_table_names():
        op.drop_index('ix_favorites_item_id', table_name='favorites')
        op.drop_table('favorites')
