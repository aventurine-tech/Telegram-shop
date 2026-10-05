"""shipping methods

Revision ID: d1f6b8c4e5a7
Revises: c9e5a7b3d4f6
Create Date: 2026-10-14 12:00:00.000000

``shipping_methods`` (a way to deliver, with a price and an optional free-delivery threshold) and, on ``orders``,
the chosen method's name and the delivery fee (already included in ``total``).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = 'd1f6b8c4e5a7'
down_revision: Union[str, None] = 'c9e5a7b3d4f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    if 'shipping_methods' not in inspector.get_table_names():
        op.create_table(
            'shipping_methods',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('name', sa.String(length=100), nullable=False, unique=True),
            sa.Column('name_en', sa.String(length=100), nullable=True),
            sa.Column('name_ru', sa.String(length=100), nullable=True),
            sa.Column('name_ro', sa.String(length=100), nullable=True),
            sa.Column('price', sa.Numeric(12, 2), nullable=False, server_default='0'),
            sa.Column('free_from', sa.Numeric(12, 2), nullable=True),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column('position', sa.Integer(), nullable=False, server_default='0'),
            sa.CheckConstraint('price >= 0', name='ck_shipping_price_nonneg'),
            sa.CheckConstraint('free_from IS NULL OR free_from >= 0', name='ck_shipping_free_from_nonneg'),
        )
    present = {c['name'] for c in inspector.get_columns('orders')}
    if 'shipping_name' not in present:
        op.add_column('orders', sa.Column('shipping_name', sa.String(length=100), nullable=True))
    if 'delivery_fee' not in present:
        op.add_column('orders', sa.Column('delivery_fee', sa.Numeric(12, 2), nullable=False, server_default='0'))


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    present = {c['name'] for c in inspector.get_columns('orders')}
    if 'delivery_fee' in present:
        op.drop_column('orders', 'delivery_fee')
    if 'shipping_name' in present:
        op.drop_column('orders', 'shipping_name')
    if 'shipping_methods' in inspector.get_table_names():
        op.drop_table('shipping_methods')
