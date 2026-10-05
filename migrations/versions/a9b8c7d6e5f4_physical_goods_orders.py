"""physical goods: stock counter, orders, order items

Revision ID: a9b8c7d6e5f4
Revises: d7e8f9a0b1c2
Create Date: 2026-10-05 12:00:00.000000

Turns the digital-goods schema into a physical-goods one:

* ``goods.stock`` replaces the per-unit ``item_values`` rows (seeded with the number of
  finite rows each product had; an "infinite" product becomes a large stock).
* ``orders`` / ``order_items`` replace ``bought_goods``.
* ``payments`` (CryptoPay / Stars / Telegram Payments bookkeeping) is dropped.
* ``ORDERS_MANAGE`` (1024) is granted to every role that can manage the catalog.

Digital purchase history (``bought_goods``) and stock values are discarded: they hold
account/key secrets that have no meaning in a physical shop. Downgrade restores the
empty tables only.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = 'a9b8c7d6e5f4'
down_revision: Union[str, None] = 'd7e8f9a0b1c2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ORDERS_MANAGE = 1 << 10
CATALOG_MANAGE = 1 << 4
UNLIMITED_STOCK = 9999


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    # --- goods.stock ---------------------------------------------------------
    goods_cols = {c['name'] for c in inspector.get_columns('goods')}
    if 'stock' not in goods_cols:
        op.add_column('goods', sa.Column('stock', sa.Integer(), nullable=False, server_default='0'))
        if 'item_values' in tables:
            op.execute(sa.text(
                "UPDATE goods SET stock = CASE "
                "WHEN EXISTS (SELECT 1 FROM item_values v WHERE v.item_id = goods.id AND v.is_infinity) "
                f"THEN {UNLIMITED_STOCK} "
                "ELSE (SELECT COUNT(*) FROM item_values v WHERE v.item_id = goods.id) END"
            ))
        op.create_check_constraint('ck_goods_stock_nonneg', 'goods', 'stock >= 0')

    # --- orders / order_items ------------------------------------------------
    if 'orders' not in tables:
        op.create_table(
            'orders',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.BigInteger(), nullable=True),
            sa.Column('status', sa.String(16), nullable=False),
            sa.Column('payment_method', sa.String(16), nullable=False),
            sa.Column('payment_status', sa.String(24), nullable=False),
            sa.Column('fulfillment', sa.String(16), nullable=False),
            sa.Column('customer_name', sa.String(100), nullable=False),
            sa.Column('phone', sa.String(32), nullable=False),
            sa.Column('address', sa.Text(), nullable=True),
            sa.Column('comment', sa.Text(), nullable=True),
            sa.Column('total', sa.Numeric(12, 2), nullable=False),
            sa.Column('balance_used', sa.Numeric(12, 2), nullable=False, server_default='0'),
            sa.Column('payment_proof', sa.String(256), nullable=True),
            sa.Column('pay_by', sa.DateTime(timezone=True), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.PrimaryKeyConstraint('id'),
            sa.ForeignKeyConstraint(['user_id'], ['users.telegram_id'], ondelete='SET NULL'),
            sa.CheckConstraint('total >= 0', name='ck_orders_total_nonneg'),
            sa.CheckConstraint('balance_used >= 0 AND balance_used <= total',
                               name='ck_orders_balance_used_range'),
        )
        op.create_index('ix_orders_user_id', 'orders', ['user_id'])
        op.create_index('ix_orders_status_created_id', 'orders', ['status', 'created_at', 'id'])
        op.create_index('ix_orders_user_created_id', 'orders', ['user_id', 'created_at', 'id'])
        op.create_index('ix_orders_payment_status_pay_by', 'orders', ['payment_status', 'pay_by'])

    if 'order_items' not in tables:
        op.create_table(
            'order_items',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('order_id', sa.Integer(), nullable=False),
            sa.Column('item_id', sa.Integer(), nullable=True),
            sa.Column('item_name', sa.String(100), nullable=False),
            sa.Column('quantity', sa.Integer(), nullable=False),
            sa.Column('unit_price', sa.Numeric(12, 2), nullable=False),
            sa.Column('line_total', sa.Numeric(12, 2), nullable=False),
            sa.PrimaryKeyConstraint('id'),
            sa.ForeignKeyConstraint(['order_id'], ['orders.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['item_id'], ['goods.id'], ondelete='SET NULL'),
            sa.CheckConstraint('quantity > 0', name='ck_order_items_quantity_positive'),
        )
        op.create_index('ix_order_items_order_id', 'order_items', ['order_id'])
        op.create_index('ix_order_items_item_id', 'order_items', ['item_id'])
        op.create_index('ix_order_items_item_name', 'order_items', ['item_name'])

    # --- drop the digital-goods tables ---------------------------------------
    for table in ('item_values', 'bought_goods', 'payments'):
        if table in tables:
            op.drop_table(table)

    # --- permission: whoever manages the catalog can manage orders -----------
    op.execute(sa.text(
        f"UPDATE roles SET permissions = permissions + {ORDERS_MANAGE} "
        f"WHERE (permissions & {CATALOG_MANAGE}) = {CATALOG_MANAGE} "
        f"AND (permissions & {ORDERS_MANAGE}) = 0"
    ))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    op.execute(sa.text(
        f"UPDATE roles SET permissions = permissions - {ORDERS_MANAGE} "
        f"WHERE (permissions & {ORDERS_MANAGE}) = {ORDERS_MANAGE}"
    ))

    if 'item_values' not in tables:
        op.create_table(
            'item_values',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('item_id', sa.Integer(), nullable=False),
            sa.Column('value', sa.Text(), nullable=True),
            sa.Column('is_infinity', sa.Boolean(), nullable=False),
            sa.PrimaryKeyConstraint('id'),
            sa.ForeignKeyConstraint(['item_id'], ['goods.id'], ondelete='CASCADE'),
            sa.UniqueConstraint('item_id', 'value', name='uq_item_value_per_item'),
        )
        op.create_index('ix_item_values_item_id', 'item_values', ['item_id'])
        op.create_index('ix_item_values_item_inf', 'item_values', ['item_id', 'is_infinity'])
    if 'bought_goods' not in tables:
        op.create_table(
            'bought_goods',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('item_name', sa.String(100), nullable=False),
            sa.Column('value', sa.Text(), nullable=False),
            sa.Column('price', sa.Numeric(12, 2), nullable=False),
            sa.Column('buyer_id', sa.BigInteger(), nullable=True),
            sa.Column('bought_datetime', sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.func.now()),
            sa.Column('unique_id', sa.BigInteger(), nullable=False),
            sa.PrimaryKeyConstraint('id'),
            sa.ForeignKeyConstraint(['buyer_id'], ['users.telegram_id'], ondelete='SET NULL'),
            sa.UniqueConstraint('unique_id'),
        )
    if 'payments' not in tables:
        op.create_table(
            'payments',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('provider', sa.String(32), nullable=False),
            sa.Column('external_id', sa.String(128), nullable=False),
            sa.Column('user_id', sa.BigInteger(), nullable=True),
            sa.Column('amount', sa.Numeric(12, 2), nullable=False),
            sa.Column('currency', sa.String(8), nullable=False),
            sa.Column('status', sa.String(16), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.PrimaryKeyConstraint('id'),
            sa.ForeignKeyConstraint(['user_id'], ['users.telegram_id'], ondelete='SET NULL'),
            sa.UniqueConstraint('provider', 'external_id', name='uq_payment_provider_ext'),
        )

    for table in ('order_items', 'orders'):
        if table in tables:
            op.drop_table(table)

    op.drop_constraint('ck_goods_stock_nonneg', 'goods', type_='check')
    op.drop_column('goods', 'stock')
