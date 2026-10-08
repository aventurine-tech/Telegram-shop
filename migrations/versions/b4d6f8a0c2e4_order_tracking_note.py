"""order tracking note

Revision ID: b4d6f8a0c2e4
Revises: a9c4e2b7d1f3
Create Date: 2026-10-18 12:00:00.000000

``orders.tracking_note``: the staff's note for the customer (courier, parcel number, pickup time …).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = 'b4d6f8a0c2e4'
down_revision: Union[str, None] = 'a9c4e2b7d1f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    present = {c['name'] for c in inspect(op.get_bind()).get_columns('orders')}
    if 'tracking_note' not in present:
        op.add_column('orders', sa.Column('tracking_note', sa.String(length=300), nullable=True))


def downgrade() -> None:
    present = {c['name'] for c in inspect(op.get_bind()).get_columns('orders')}
    if 'tracking_note' in present:
        op.drop_column('orders', 'tracking_note')
