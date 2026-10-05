"""per-user language and web panel accounts

Revision ID: c9d8e7f6a5b4
Revises: b8c7d6e5f4a3
Create Date: 2026-10-07 12:00:00.000000

* ``users.language`` — the interface language a Telegram user picked (NULL = not asked yet).
* ``web_users`` — logins for the web panel (hashed passwords, admin/staff role, language).
  The first Admin is created at startup from ADMIN_USERNAME/ADMIN_PASSWORD.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = 'c9d8e7f6a5b4'
down_revision: Union[str, None] = 'b8c7d6e5f4a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    if 'language' not in {c['name'] for c in inspector.get_columns('users')}:
        op.add_column('users', sa.Column('language', sa.String(2), nullable=True))
        op.create_check_constraint('ck_users_language', 'users', "language IN ('en','ru','ro')")

    if 'web_users' not in inspector.get_table_names():
        op.create_table(
            'web_users',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('username', sa.String(64), nullable=False),
            sa.Column('password_hash', sa.String(256), nullable=False),
            sa.Column('role', sa.String(8), nullable=False),
            sa.Column('language', sa.String(2), nullable=True),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('username', name='uq_web_users_username'),
            sa.CheckConstraint("role IN ('admin','staff')", name='ck_web_users_role'),
            sa.CheckConstraint("language IS NULL OR language IN ('en','ru','ro')", name='ck_web_users_language'),
        )


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    if 'web_users' in inspector.get_table_names():
        op.drop_table('web_users')
    if 'language' in {c['name'] for c in inspector.get_columns('users')}:
        op.drop_constraint('ck_users_language', 'users', type_='check')
        op.drop_column('users', 'language')
