"""mailing opt-out, recipient log, resend-to-failed

Revision ID: d6f8b0c2e4a6
Revises: c5e7a9b1d3f5
Create Date: 2026-10-20 12:00:00.000000

``users.mailing_optout`` (people who asked for no mailings), ``mailing_recipients`` (one row per person per mailing with
the outcome) and ``mailings.retry_of`` (a mailing that targets whoever an earlier one failed to reach).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = 'd6f8b0c2e4a6'
down_revision: Union[str, None] = 'c5e7a9b1d3f5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    if 'mailing_optout' not in {c['name'] for c in inspector.get_columns('users')}:
        op.add_column('users', sa.Column('mailing_optout', sa.Boolean(), nullable=False, server_default=sa.false()))
    if 'retry_of' not in {c['name'] for c in inspector.get_columns('mailings')}:
        op.add_column('mailings', sa.Column('retry_of', sa.Integer(), nullable=True))
        op.create_foreign_key('fk_mailings_retry_of', 'mailings', 'mailings', ['retry_of'], ['id'], ondelete='SET NULL')
    if 'mailing_recipients' not in inspector.get_table_names():
        op.create_table(
            'mailing_recipients',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('mailing_id', sa.Integer(), sa.ForeignKey('mailings.id', ondelete='CASCADE'), nullable=False),
            sa.Column('user_id', sa.BigInteger(), nullable=False),
            sa.Column('outcome', sa.String(length=8), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.CheckConstraint("outcome IN ('sent','blocked','failed')", name='ck_mailing_recipients_outcome'),
        )
        op.create_index('ix_mailing_recipients_mailing_outcome', 'mailing_recipients',
                        ['mailing_id', 'outcome', 'id'])


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    if 'mailing_recipients' in inspector.get_table_names():
        op.drop_index('ix_mailing_recipients_mailing_outcome', table_name='mailing_recipients')
        op.drop_table('mailing_recipients')
    if 'retry_of' in {c['name'] for c in inspector.get_columns('mailings')}:
        op.drop_constraint('fk_mailings_retry_of', 'mailings', type_='foreignkey')
        op.drop_column('mailings', 'retry_of')
    if 'mailing_optout' in {c['name'] for c in inspector.get_columns('users')}:
        op.drop_column('users', 'mailing_optout')
