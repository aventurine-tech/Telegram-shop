"""product images

Revision ID: b8c7d6e5f4a3
Revises: a9b8c7d6e5f4
Create Date: 2026-10-06 12:00:00.000000

One optional picture per product, stored unchanged, apart from `goods` so the bytes never
travel with item lookups or the Redis item cache. `file_id` caches Telegram's reference.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = 'b8c7d6e5f4a3'
down_revision: Union[str, None] = 'a9b8c7d6e5f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if 'product_images' in inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        'product_images',
        sa.Column('item_id', sa.Integer(), nullable=False),
        sa.Column('data', sa.LargeBinary(), nullable=False),
        sa.Column('file_id', sa.String(256), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('item_id'),
        sa.ForeignKeyConstraint(['item_id'], ['goods.id'], ondelete='CASCADE'),
    )


def downgrade() -> None:
    if 'product_images' in inspect(op.get_bind()).get_table_names():
        op.drop_table('product_images')
