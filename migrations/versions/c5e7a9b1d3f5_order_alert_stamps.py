"""order alert stamps

Revision ID: c5e7a9b1d3f5
Revises: b4d6f8a0c2e4
Create Date: 2026-10-19 12:00:00.000000

``orders.reminder_sent_at`` (the customer's "pay soon" reminder) and ``orders.staff_alerted_at`` (staff's "this order is
waiting" alert): each background alert goes out once per order.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = 'c5e7a9b1d3f5'
down_revision: Union[str, None] = 'b4d6f8a0c2e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLUMNS = ('reminder_sent_at', 'staff_alerted_at')


def upgrade() -> None:
    present = {c['name'] for c in inspect(op.get_bind()).get_columns('orders')}
    for name in _COLUMNS:
        if name not in present:
            op.add_column('orders', sa.Column(name, sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    present = {c['name'] for c in inspect(op.get_bind()).get_columns('orders')}
    for name in reversed(_COLUMNS):
        if name in present:
            op.drop_column('orders', name)
