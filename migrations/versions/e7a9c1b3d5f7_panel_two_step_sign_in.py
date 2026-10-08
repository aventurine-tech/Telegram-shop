"""optional two-step sign-in for panel accounts

Revision ID: e7a9c1b3d5f7
Revises: d6f8b0c2e4a6
Create Date: 2026-10-21 12:00:00.000000

``web_users.totp_secret`` (encrypted), ``totp_enabled``, ``totp_last_step`` (replay guard) and ``totp_backup`` (hashed
one-time backup codes). Everyone starts with it off.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = 'e7a9c1b3d5f7'
down_revision: Union[str, None] = 'd6f8b0c2e4a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    have = {c['name'] for c in inspect(op.get_bind()).get_columns('web_users')}
    if 'totp_secret' not in have:
        op.add_column('web_users', sa.Column('totp_secret', sa.String(length=255), nullable=True))
    if 'totp_enabled' not in have:
        op.add_column('web_users', sa.Column('totp_enabled', sa.Boolean(), nullable=False, server_default=sa.false()))
    if 'totp_last_step' not in have:
        op.add_column('web_users', sa.Column('totp_last_step', sa.BigInteger(), nullable=True))
    if 'totp_backup' not in have:
        op.add_column('web_users', sa.Column('totp_backup', sa.Text(), nullable=True))


def downgrade() -> None:
    have = {c['name'] for c in inspect(op.get_bind()).get_columns('web_users')}
    for name in ('totp_backup', 'totp_last_step', 'totp_enabled', 'totp_secret'):
        if name in have:
            op.drop_column('web_users', name)
