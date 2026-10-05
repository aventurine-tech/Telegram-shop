import csv
import datetime
import io
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select

from bot.database.main import Database
from tests.factories import add_operation
from bot.database.models.main import Orders, OrderItems, User
from bot.web.export import (
    BATCH_SIZE, _sanitize_cell, _parse_date_params, _check_auth, _stream_csv,
    export_users, export_orders, export_order_items, export_operations,
)

NOW = datetime.datetime.now(datetime.timezone.utc)


async def _add_order(user_id, *, customer="Ann", total=100, created_at=NOW, lines=(("Lamp", 1, 100),)):
    """Insert an order with its lines; returns the order id."""
    async with Database().session() as s:
        order = Orders(
            user_id=user_id, status="new", payment_method="cod", payment_status="unpaid",
            fulfillment="pickup", customer_name=customer, phone="123456", total=total,
            balance_used=0, created_at=created_at,
        )
        s.add(order)
        await s.flush()
        for name, qty, line_total in lines:
            s.add(OrderItems(order_id=order.id, item_name=name, quantity=qty,
                             unit_price=line_total / qty, line_total=line_total))
        return order.id


def _request(session=None, **query_params):
    """A Starlette Request stand-in carrying a session and query params."""
    req = MagicMock()
    req.session = {} if session is None else session
    req.query_params = query_params
    return req


async def _collect(response):
    """Join a StreamingResponse body into one CSV string."""
    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk)
    return "".join(chunks)


class TestSanitizeCell:
    """Spreadsheets execute a cell starting with these characters, so an item
    name or a Telegram username can smuggle a formula into an exported CSV."""

    @pytest.mark.parametrize("raw", ["=", "+", "-", "@", "\t", "\r"])
    def test_formula_prefixes_are_quoted(self, raw):
        value = f"{raw}cmd|' /C calc'!A0"
        assert _sanitize_cell(value) == "'" + value

    @pytest.mark.parametrize("raw,expected", [
        (None, ""),                    # NULL columns export as empty, not "None"
        ("plain text", "plain text"),
        ("na=me", "na=me"),            # only a *leading* char is dangerous
        (123, "123"),
        (Decimal("10.50"), "10.50"),
    ])
    def test_safe_values_pass_through(self, raw, expected):
        assert _sanitize_cell(raw) == expected


class TestParseDateParams:

    @pytest.mark.parametrize("params,expected_from,expected_to", [
        ({}, None, None),
        ({"from": "2026-01-15"}, datetime.datetime(2026, 1, 15, tzinfo=datetime.timezone.utc), None),
        ({"to": "2026-02-01"}, None, datetime.datetime(2026, 2, 1, tzinfo=datetime.timezone.utc)),
        # Garbage is ignored rather than raising a 500 at the user.
        ({"from": "not-a-date"}, None, None),
        ({"from": "2026-13-45"}, None, None),
        ({"from": ""}, None, None),
    ])
    def test_parsing(self, params, expected_from, expected_to):
        assert _parse_date_params(_request(**params)) == (expected_from, expected_to)


class TestCheckAuth:

    @pytest.mark.parametrize("session,expected", [
        ({"authenticated": True}, True),
        ({"authenticated": False}, False),
        ({}, False),  # no session key at all
    ])
    def test_auth(self, session, expected):
        assert _check_auth(_request(session=session)) is expected


class TestExportEndpointsRequireAuth:

    @pytest.mark.parametrize("endpoint", [
        export_users, export_orders, export_order_items, export_operations,
    ])
    async def test_unauthenticated_request_is_rejected(self, endpoint):
        response = await endpoint(_request())
        assert response.status_code == 401


class TestStreamCsv:

    async def test_header_and_rows(self, user_factory):
        await user_factory(telegram_id=770001, balance=250)

        query = select(User.telegram_id, User.balance).order_by(User.telegram_id)
        chunks = [
            c async for c in _stream_csv(
                query, ["telegram_id", "balance"], Database().session, User.telegram_id
            )
        ]

        rows = list(csv.reader(io.StringIO("".join(chunks))))
        assert rows[0] == ["telegram_id", "balance"]
        assert rows[1] == ["770001", "250.00"]

    async def test_empty_table_still_emits_the_header(self):
        query = select(User.telegram_id).order_by(User.telegram_id)
        chunks = [
            c async for c in _stream_csv(
                query, ["telegram_id"], Database().session, User.telegram_id
            )
        ]
        assert list(csv.reader(io.StringIO("".join(chunks)))) == [["telegram_id"]]

    async def test_keyset_pagination_walks_past_the_batch_size(self, user_factory, monkeypatch):
        # Shrink the batch so three rows span two batches and the keyset
        # cursor (`WHERE id > last`) has to advance to terminate.
        monkeypatch.setattr('bot.web.export.BATCH_SIZE', 2)

        for tid in (770010, 770011, 770012):
            await user_factory(telegram_id=tid)

        query = select(User.telegram_id).order_by(User.telegram_id)
        chunks = [
            c async for c in _stream_csv(
                query, ["telegram_id"], Database().session, User.telegram_id
            )
        ]

        rows = list(csv.reader(io.StringIO("".join(chunks))))
        assert rows[0] == ["telegram_id"]
        assert [r[0] for r in rows[1:]] == ["770010", "770011", "770012"]

    async def test_batch_size_default_is_not_accidentally_tiny(self):
        assert BATCH_SIZE == 1000

    async def test_exported_customer_name_cannot_carry_a_formula(self, user_factory):
        """End-to-end: a hostile customer name reaches the CSV neutralized."""
        await user_factory(telegram_id=770020)
        await _add_order(770020, customer="=HYPERLINK(\"http://evil\",\"click\")")

        response = await export_orders(_request(session={"authenticated": True}))
        body = await _collect(response)

        rows = list(csv.reader(io.StringIO(body)))
        names = [r[rows[0].index("customer_name")] for r in rows[1:]]
        assert names == ["'=HYPERLINK(\"http://evil\",\"click\")"]

    async def test_exported_product_name_cannot_carry_a_formula(self, user_factory):
        await user_factory(telegram_id=770021)
        await _add_order(770021, lines=(("@SUM(1+1)", 1, 100),))

        response = await export_order_items(_request(session={"authenticated": True}))
        rows = list(csv.reader(io.StringIO(await _collect(response))))

        assert [r[2] for r in rows[1:]] == ["'@SUM(1+1)"]


class TestExportEndpoints:

    AUTHED = {"authenticated": True}

    async def test_users_export_contains_the_seeded_user(self, user_factory):
        await user_factory(telegram_id=770030, balance=99)

        response = await export_users(_request(session=self.AUTHED))
        rows = list(csv.reader(io.StringIO(await _collect(response))))

        assert rows[0][0] == "telegram_id"
        assert [r[0] for r in rows[1:]] == ["770030"]
        assert response.headers["content-disposition"] == "attachment; filename=users.csv"

    async def test_operations_export(self, user_factory):
        await user_factory(telegram_id=770040)
        await add_operation(770040, 150, NOW)

        response = await export_operations(_request(session=self.AUTHED))
        rows = list(csv.reader(io.StringIO(await _collect(response))))

        assert rows[0] == ["id", "user_id", "operation_value", "operation_time"]
        assert rows[1][1] == "770040"
        assert Decimal(rows[1][2]) == Decimal("150")

    async def test_orders_export(self, user_factory):
        await user_factory(telegram_id=770050)
        order_id = await _add_order(770050, total=100)

        response = await export_orders(_request(session=self.AUTHED))
        rows = list(csv.reader(io.StringIO(await _collect(response))))

        assert rows[0][:4] == ["id", "user_id", "status", "payment_method"]
        assert rows[1][:5] == [str(order_id), "770050", "new", "cod", "unpaid"]
        assert Decimal(rows[1][rows[0].index("total")]) == Decimal("100")
        assert response.headers["content-disposition"] == "attachment; filename=orders.csv"

    async def test_order_items_export(self, user_factory):
        await user_factory(telegram_id=770051)
        order_id = await _add_order(770051, total=300, lines=(("Lamp", 2, 200), ("Cable", 1, 100)))

        response = await export_order_items(_request(session=self.AUTHED))
        rows = list(csv.reader(io.StringIO(await _collect(response))))

        assert rows[0] == ["id", "order_id", "item_name", "quantity", "unit_price", "line_total"]
        assert [(r[1], r[2], r[3]) for r in rows[1:]] == [
            (str(order_id), "Lamp", "2"), (str(order_id), "Cable", "1"),
        ]

    async def test_order_date_filter_applies_to_order_and_its_lines(self, user_factory):
        await user_factory(telegram_id=770052)
        old = NOW - datetime.timedelta(days=10)
        await _add_order(770052, created_at=old)

        cutoff = (NOW - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
        for endpoint in (export_orders, export_order_items):
            response = await endpoint(_request(session=self.AUTHED, **{"from": cutoff}))
            rows = list(csv.reader(io.StringIO(await _collect(response))))
            assert len(rows) == 1  # header only

    async def test_date_filter_excludes_rows_outside_the_window(self, user_factory):
        await user_factory(telegram_id=770060)
        await add_operation(770060, 10, NOW)

        far_future = (NOW + datetime.timedelta(days=2)).strftime("%Y-%m-%d")
        response = await export_operations(
            _request(session=self.AUTHED, **{"from": far_future})
        )
        rows = list(csv.reader(io.StringIO(await _collect(response))))

        # Header only — the operation predates the window.
        assert len(rows) == 1
