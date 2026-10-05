"""mailings

Revision ID: b8d4f6a2c3e5
Revises: a7c3e5f1b2d4
Create Date: 2026-10-12 12:00:00.000000

The ``mailings`` table (web-panel mass messages: text, picture, audience, schedule, counters) and
``web_users.telegram_id`` (where a person's "send me a test" goes).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = 'b8d4f6a2c3e5'
down_revision: Union[str, None] = 'a7c3e5f1b2d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    if 'mailings' not in inspector.get_table_names():
        op.create_table(
            'mailings',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('title', sa.String(length=200), nullable=False),
            sa.Column('text', sa.Text(), nullable=False),
            sa.Column('image', sa.LargeBinary(), nullable=True),
            sa.Column('image_file_id', sa.String(length=256), nullable=True),
            sa.Column('segment', sa.String(length=16), nullable=False, server_default='all'),
            sa.Column('status', sa.String(length=12), nullable=False, server_default='draft'),
            sa.Column('scheduled_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('disable_preview', sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column('silent', sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column('protect_content', sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column('total', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('sent', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('blocked', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('failed', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('created_by', sa.String(length=64), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.CheckConstraint("status IN ('draft','scheduled','sending','sent','cancelled','failed')",
                               name='ck_mailings_status'),
            sa.CheckConstraint("segment IN ('all','lang_ro','lang_ru','lang_en','with_orders','without_orders')",
                               name='ck_mailings_segment'),
        )
        op.create_index('ix_mailings_status', 'mailings', ['status'])
    if 'telegram_id' not in {c['name'] for c in inspector.get_columns('web_users')}:
        with op.batch_alter_table('web_users') as batch:
            batch.add_column(sa.Column('telegram_id', sa.BigInteger(), nullable=True))


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    if 'telegram_id' in {c['name'] for c in inspector.get_columns('web_users')}:
        with op.batch_alter_table('web_users') as batch:
            batch.drop_column('telegram_id')
    if 'mailings' in inspector.get_table_names():
        op.drop_index('ix_mailings_status', table_name='mailings')
        op.drop_table('mailings')
