"""remember people Telegram says cannot be reached

Revision ID: f8c0e2a4b6d8
Revises: e7a9c1b3d5f7
Create Date: 2026-11-24 20:00:00.000000

``users.unreachable_since``: set when Telegram refuses a message to the person (they blocked the bot or deleted their
account), cleared when they use the bot again. Mailings and broadcasts skip these people.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = 'f8c0e2a4b6d8'
down_revision: Union[str, None] = 'e7a9c1b3d5f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    have = {c['name'] for c in inspect(op.get_bind()).get_columns('users')}
    if 'unreachable_since' not in have:
        op.add_column('users', sa.Column('unreachable_since', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    have = {c['name'] for c in inspect(op.get_bind()).get_columns('users')}
    if 'unreachable_since' in have:
        op.drop_column('users', 'unreachable_since')
