"""Weight options on the customer side: selector, fallbacks, Back, gateway head, reviews, cart."""
import io
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from PIL import Image
from sqlalchemy import update as sa_update

from bot.database.main import Database
from bot.database.methods.create import (
    create_category, create_item, create_item_option, add_to_cart,
)
from bot.database.methods.product_images import set_item_image
from bot.database.methods.read import get_cart_items, get_item_info
from bot.database.models.main import Goods, Orders, OrderItems
from bot.handlers.user import shop_and_goods as shop
from bot.handlers.user.cart import add_to_cart_handler, view_cart_handler
from bot.handlers.user.shop_and_goods import (
    _render_item_page, item_info_callback_handler, option_callback_handler,
    start_review_handler, navigate_goods,
)
from bot.i18n import use_language
from bot.keyboards.inline import item_info
from bot.middleware.rate_limit import RateLimitMiddleware


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), (10, 200, 10)).save(buf, "PNG")
    return buf.getvalue()


def _rows(markup):
    return [[(b.text, b.callback_data) for b in row] for row in markup.inline_keyboard]


def _flat(markup):
    return [b for row in _rows(markup) for b in row]


async def _family(stock_50=5, stock_200=2, head_price=0):
    await create_category("Tobacco")
    await create_item("SOLO 11", "Fruity", head_price, "Tobacco", names={"ro": "SOLO 11 ro", "en": "SOLO 11 en"},
                      descriptions={"en": "Fruity en"})
    await create_item_option("SOLO 11", "50 g", 90, stock_50)
    await create_item_option("SOLO 11", "200 g", 300, stock_200)
    return {n: (await get_item_info(n))["id"] for n in ("SOLO 11", "SOLO 11 · 50 g", "SOLO 11 · 200 g")}


class TestSelector:

    async def test_opening_head_preselects_first_in_stock_option(self, make_callback_query, fsm_context):
        ids = await _family(stock_50=0, stock_200=2)
        await fsm_context.update_data(goods_page_items=["SOLO 11"], goods_page_num=0)
        call = make_callback_query(data="itm:0:0")
        await item_info_callback_handler(call, fsm_context)

        assert (await fsm_context.get_data())["csrf_item"] == "SOLO 11 · 200 g"
        markup = call.message.edit_text.call_args[1]["reply_markup"]
        assert _rows(markup)[0] == [("50 g", f"opt:{ids['SOLO 11 · 50 g']}"),
                                    ("✅ 200 g", f"opt:{ids['SOLO 11 · 200 g']}")]
        assert "gp_0" in [cb for _t, cb in _flat(markup)]

    async def test_all_out_of_stock_preselects_first(self, make_callback_query, fsm_context):
        await _family(stock_50=0, stock_200=0)
        await fsm_context.update_data(goods_page_items=["SOLO 11"], goods_page_num=0)
        await item_info_callback_handler(make_callback_query(data="itm:0:0"), fsm_context)
        assert (await fsm_context.get_data())["csrf_item"] == "SOLO 11 · 50 g"

    async def test_standalone_item_has_no_selector(self, make_callback_query, fsm_context, item_factory):
        await item_factory(name="Plain", price=10, stock=1)
        call = make_callback_query(data="x")
        await _render_item_page(call, fsm_context, "Plain", "gp_0", user_id=1)
        assert not any(cb.startswith("opt:") for _t, cb in _flat(call.message.edit_text.call_args[1]["reply_markup"]))

    async def test_tapping_option_opens_its_card_and_keeps_back(self, make_callback_query, fsm_context):
        ids = await _family()
        await fsm_context.update_data(csrf_item="SOLO 11 · 50 g", item_back_data="gp_3")
        call = make_callback_query(data=f"opt:{ids['SOLO 11 · 200 g']}")
        await option_callback_handler(call, fsm_context)

        data = await fsm_context.get_data()
        assert data["csrf_item"] == "SOLO 11 · 200 g" and data["item_back_data"] == "gp_3"
        text = call.message.edit_text.call_args[0][0]
        assert "SOLO 11 · 200 g" in text and "'amount': Decimal('300.00')" in text and "'count': 2" in text
        markup = call.message.edit_text.call_args[1]["reply_markup"]
        assert ("✅ 200 g", f"opt:{ids['SOLO 11 · 200 g']}") in _flat(markup)
        cbs = [cb for _t, cb in _flat(markup)]
        assert "gp_3" in cbs and "add_to_cart" in cbs

    async def test_option_of_another_family_or_a_head_is_refused(self, make_callback_query, fsm_context,
                                                                 item_factory):
        ids = await _family()
        await item_factory(name="Other", price=5, stock=1)
        await fsm_context.update_data(csrf_item="Other")
        for gid in (ids["SOLO 11 · 50 g"], ids["SOLO 11"], 99999):
            call = make_callback_query(data=f"opt:{gid}")
            await option_callback_handler(call, fsm_context)
            call.answer.assert_awaited_once_with("shop.item.not_found", show_alert=True)
        call = make_callback_query(data="opt:abc")
        await option_callback_handler(call, fsm_context)
        call.answer.assert_awaited_once_with("shop.item.not_found", show_alert=True)

    def test_callback_fits_telegram_limit_and_rate_limit_mapping(self):
        assert len(f"opt:{2 ** 63}".encode()) <= 64
        mw = RateLimitMiddleware()
        from aiogram.types import CallbackQuery
        ev = MagicMock(spec=CallbackQuery)
        ev.data = "opt:12"
        assert mw._get_action_from_event(ev) == "shop_view"

    def test_opt_prefix_has_a_handler(self):
        from tests.test_admin_pagination import TestEveryNavPrefixHasAHandler as T
        assert T()._matches("opt:12") is True

    def test_many_options_wrap_into_rows_of_three(self):
        kb = item_info("gp_0", options=[(i, f"{i} g", i == 1) for i in range(1, 8)])
        rows = _rows(kb)
        assert [len(r) for r in rows[:3]] == [3, 3, 1] and all(cb.startswith("opt:") for _t, cb in sum(rows[:3], []))


class TestFallbacks:

    async def test_option_shows_heads_description_per_language(self, make_callback_query, fsm_context):
        await _family()
        for lang, desc in (("en", "Fruity en"), ("ro", "Fruity")):
            call = make_callback_query(data="x")
            with use_language(lang):
                await _render_item_page(call, fsm_context, "SOLO 11 · 50 g", "gp_0", user_id=1)
            text = call.message.edit_text.call_args[0][0]
            assert f"'description': '{desc}'" in text
            assert f"'name': 'SOLO 11 {lang} · 50 g'" in text or lang == "ro" and "SOLO 11 ro · 50 g" in text

    async def test_option_own_description_wins(self, make_callback_query, fsm_context):
        await create_category("C")
        await create_item("H", "head text", 0, "C")
        await create_item_option("H", "1 kg", 10, 1)
        async with Database().session() as sess:
            await sess.execute(sa_update(Goods).where(Goods.name == "H · 1 kg").values(description_ro="own text"))
        call = make_callback_query(data="x")
        with use_language("ro"):
            await _render_item_page(call, fsm_context, "H · 1 kg", "gp_0", user_id=1)
        assert "'description': 'own text'" in call.message.edit_text.call_args[0][0]

    async def test_option_without_picture_shows_head_picture(self, make_callback_query, fsm_context, monkeypatch):
        await _family()
        await set_item_image("SOLO 11", _png())
        sent = AsyncMock(return_value=True)
        monkeypatch.setattr(shop, "_send_card_photo", sent)
        call = make_callback_query(data="x")
        await _render_item_page(call, fsm_context, "SOLO 11 · 50 g", "gp_0", user_id=1)
        assert sent.call_args[0][1] == "SOLO 11"

    async def test_option_own_picture_wins(self, make_callback_query, fsm_context, monkeypatch):
        await _family()
        await set_item_image("SOLO 11", _png())
        await set_item_image("SOLO 11 · 50 g", _png())
        sent = AsyncMock(return_value=True)
        monkeypatch.setattr(shop, "_send_card_photo", sent)
        await _render_item_page(make_callback_query(data="x"), fsm_context, "SOLO 11 · 50 g", "gp_0", user_id=1)
        assert sent.call_args[0][1] == "SOLO 11 · 50 g"


class TestBackFromOption:

    async def test_back_goes_to_the_product_list(self, make_callback_query, fsm_context):
        ids = await _family()
        await fsm_context.update_data(goods_page_items=["SOLO 11"], goods_page_num=0, current_category="Tobacco")
        await item_info_callback_handler(make_callback_query(data="itm:0:0"), fsm_context)
        await option_callback_handler(make_callback_query(data=f"opt:{ids['SOLO 11 · 200 g']}"), fsm_context)
        assert (await fsm_context.get_data())["item_back_data"] == "gp_0"

        call = make_callback_query(data="gp_0")
        await navigate_goods(call, fsm_context)
        assert call.message.edit_text.await_count == 1      # the list, not an item card
        assert "SOLO 11 · " not in call.message.edit_text.call_args[0][0]


class TestGatewayHead:

    async def test_head_card_has_nothing_to_buy(self, make_callback_query, fsm_context):
        await _family()
        call = make_callback_query(data="x")
        await _render_item_page(call, fsm_context, "SOLO 11", "gp_0", user_id=1)
        text = call.message.edit_text.call_args[0][0]
        assert "shop.item.choose_option" in text and "shop.item.price" not in text and "in_stock" not in text
        cbs = [cb for _t, cb in _flat(call.message.edit_text.call_args[1]["reply_markup"])]
        for forbidden in ("buy_item", "add_to_cart", "apply_promo", "sub_stock"):
            assert forbidden not in cbs
        assert any(cb.startswith("opt:") for cb in cbs)

    @pytest.mark.parametrize("handler", [add_to_cart_handler])
    @pytest.mark.parametrize("head_price", [0, 50])
    async def test_cannot_add_head_with_options(self, make_callback_query, fsm_context, user_factory,
                                                handler, head_price):
        await _family(head_price=head_price)
        await user_factory(telegram_id=910001)
        await create_item_option("SOLO 11", "1 kg", 1, 1)
        await fsm_context.update_data(csrf_item="SOLO 11")
        call = make_callback_query(data="add_to_cart", user_id=910001)
        await handler(call, fsm_context)
        call.answer.assert_awaited_once_with("cart.choose_option", show_alert=True)
        assert await get_cart_items(910001) == []

    async def test_option_can_be_added(self, make_callback_query, fsm_context, user_factory):
        await _family()
        await user_factory(telegram_id=910002)
        await fsm_context.update_data(csrf_item="SOLO 11 · 50 g")
        await add_to_cart_handler(make_callback_query(data="add_to_cart", user_id=910002), fsm_context)
        assert [i["item_name"] for i in await get_cart_items(910002)] == ["SOLO 11 · 50 g"]


class TestCartAndReviews:

    async def test_cart_shows_composite_name_per_language(self, make_callback_query, fsm_context, user_factory):
        await _family()
        await user_factory(telegram_id=910003)
        await add_to_cart(910003, "SOLO 11 · 50 g")
        for lang, name in (("en", "SOLO 11 en · 50 g"), ("ro", "SOLO 11 ro · 50 g"), ("ru", "SOLO 11 · 50 g")):
            call = make_callback_query(data="cart", user_id=910003)
            with use_language(lang):
                await view_cart_handler(call, fsm_context)
            assert f"'name': '{name}'" in call.message.edit_text.call_args[0][0]
            assert f"{name} ×1" in [t for t, _ in _flat(call.message.edit_text.call_args[1]["reply_markup"])]

    async def test_review_flow_from_option_card_counts_sibling_purchase(
            self, make_callback_query, fsm_context, user_factory, monkeypatch):
        monkeypatch.setattr(shop.EnvKeys, "REVIEWS_ENABLED", "1")
        await _family()
        await user_factory(telegram_id=910004)
        async with Database().session() as s:
            order = Orders(user_id=910004, status="completed", payment_method="cod", payment_status="paid",
                           fulfillment="pickup", customer_name="A", phone="123456", total=90, balance_used=0)
            s.add(order)
            await s.flush()
            s.add(OrderItems(order_id=order.id, item_name="SOLO 11 · 50 g", quantity=1,
                             unit_price=90, line_total=90))

        # on the other option's card the review button is offered and the flow starts
        card = make_callback_query(data="x", user_id=910004)
        await _render_item_page(card, fsm_context, "SOLO 11 · 200 g", "gp_0", user_id=910004)
        assert "review" in [cb for _t, cb in _flat(card.message.edit_text.call_args[1]["reply_markup"])]

        await fsm_context.update_data(csrf_item="SOLO 11 · 200 g")
        call = make_callback_query(data="review", user_id=910004)
        await start_review_handler(call, fsm_context)
        call.answer.assert_not_awaited()
        assert "SOLO 11" in call.message.edit_text.call_args[0][0]
        assert "200 g" not in call.message.edit_text.call_args[0][0]     # the prompt names the head
