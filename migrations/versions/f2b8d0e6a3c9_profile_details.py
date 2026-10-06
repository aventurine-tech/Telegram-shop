"""profile details

Revision ID: f2b8d0e6a3c9
Revises: e1a7c9d5f2b8
Create Date: 2026-10-16 12:00:00.000000

``users.contact_name`` (the name for delivery) and ``users.city``; the name is back-filled from each customer's
latest order.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = 'f2b8d0e6a3c9'
down_revision: Union[str, None] = 'e1a7c9d5f2b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    present = {c['name'] for c in inspector.get_columns('users')}
    if 'contact_name' not in present:
        op.add_column('users', sa.Column('contact_name', sa.String(length=100), nullable=True))
    if 'city' not in present:
        op.add_column('users', sa.Column('city', sa.String(length=100), nullable=True))
    op.execute("""
        UPDATE users SET contact_name = (
            SELECT o.customer_name FROM orders o WHERE o.user_id = users.telegram_id ORDER BY o.id DESC LIMIT 1)
        WHERE contact_name IS NULL
    """)


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    present = {c['name'] for c in inspector.get_columns('users')}
    for name in ('city', 'contact_name'):
        if name in present:
            op.drop_column('users', name)
