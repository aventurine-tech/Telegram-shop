"""client profiles

Revision ID: c9e5a7b3d4f6
Revises: b8d4f6a2c3e5
Create Date: 2026-10-13 12:00:00.000000

``users`` gets the person's profile: username, first/last name (from Telegram), phone, address, staff notes and
the last time they used the bot. Phone and address of existing customers are taken from their latest order.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = 'c9e5a7b3d4f6'
down_revision: Union[str, None] = 'b8d4f6a2c3e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COLUMNS = [
    ('username', sa.String(length=64)), ('first_name', sa.String(length=128)), ('last_name', sa.String(length=128)),
    ('phone', sa.String(length=32)), ('address', sa.Text()), ('notes', sa.Text()),
    ('last_seen_at', sa.DateTime(timezone=True)),
]


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    present = {c['name'] for c in inspector.get_columns('users')}
    for name, type_ in COLUMNS:
        if name not in present:
            op.add_column('users', sa.Column(name, type_, nullable=True))
    if 'ix_users_username' not in {i['name'] for i in inspector.get_indexes('users')}:
        op.create_index('ix_users_username', 'users', ['username'])
    # Contact details from each customer's most recent order (the address only from one that had an address).
    op.execute("""
        UPDATE users SET phone = (
            SELECT o.phone FROM orders o WHERE o.user_id = users.telegram_id ORDER BY o.id DESC LIMIT 1)
        WHERE phone IS NULL
    """)
    op.execute("""
        UPDATE users SET address = (
            SELECT o.address FROM orders o
            WHERE o.user_id = users.telegram_id AND o.address IS NOT NULL AND o.address <> ''
            ORDER BY o.id DESC LIMIT 1)
        WHERE address IS NULL
    """)


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    if 'ix_users_username' in {i['name'] for i in inspector.get_indexes('users')}:
        op.drop_index('ix_users_username', table_name='users')
    present = {c['name'] for c in inspector.get_columns('users')}
    for name, _ in reversed(COLUMNS):
        if name in present:
            op.drop_column('users', name)
