"""order shipping name translations

Revision ID: a9c4e2b7d1f3
Revises: f2b8d0e6a3c9
Create Date: 2026-10-17 12:00:00.000000

``orders.shipping_name_en/ru/ro``: the shipping method's translated names as they were when the order was placed, so
an order renders in the viewer's language. Old orders are back-filled from the method of the same canonical name.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = 'a9c4e2b7d1f3'
down_revision: Union[str, None] = 'f2b8d0e6a3c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLUMNS = ('shipping_name_en', 'shipping_name_ru', 'shipping_name_ro')


def upgrade() -> None:
    present = {c['name'] for c in inspect(op.get_bind()).get_columns('orders')}
    for name in _COLUMNS:
        if name not in present:
            op.add_column('orders', sa.Column(name, sa.String(length=100), nullable=True))
    for name in _COLUMNS:
        lang = name.rsplit('_', 1)[1]
        op.execute(f"""
            UPDATE orders SET {name} = (SELECT m.name_{lang} FROM shipping_methods m WHERE m.name = orders.shipping_name)
            WHERE shipping_name IS NOT NULL AND {name} IS NULL
        """)


def downgrade() -> None:
    present = {c['name'] for c in inspect(op.get_bind()).get_columns('orders')}
    for name in reversed(_COLUMNS):
        if name in present:
            op.drop_column('orders', name)
