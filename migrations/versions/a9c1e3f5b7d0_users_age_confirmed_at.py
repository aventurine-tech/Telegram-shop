"""remember when a person confirmed they are 18 or over

Revision ID: a9c1e3f5b7d0
Revises: f8c0e2a4b6d8
Create Date: 2026-11-24 21:30:00.000000

``users.age_confirmed_at``: set when the person answers "Yes" to the 18+ question the bot asks before it shows the
catalog (D-27). Empty for everyone who has not answered yet, so existing customers are asked once.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = 'a9c1e3f5b7d0'
down_revision: Union[str, None] = 'f8c0e2a4b6d8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    have = {c['name'] for c in inspect(op.get_bind()).get_columns('users')}
    if 'age_confirmed_at' not in have:
        op.add_column('users', sa.Column('age_confirmed_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    have = {c['name'] for c in inspect(op.get_bind()).get_columns('users')}
    if 'age_confirmed_at' in have:
        op.drop_column('users', 'age_confirmed_at')
