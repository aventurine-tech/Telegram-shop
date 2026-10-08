"""'Notify me' for sold-out products and options: marks in the selector, the open button on the notice."""
from unittest.mock import AsyncMock

from bot.database.methods.create import create_category, create_item, create_item_option, subscribe_to_stock
from bot.database.methods.read import get_item_info, is_subscribed_to_stock
from bot.handlers.user import shop_and_goods as shop
from bot.handlers.user.shop_and_goods import restock_open_handler
from bot.misc.services.restock_notifier import notify_restock


def _flat(markup):
    return [(b.text, b.callback_data) for row in markup.inline_keyboard for b in row]


async def _family():
    await create_category("Vapes")
    await create_item("Cherry", "Sweet", 0, "Vapes")
    await create_item_option("Cherry", "20 mg", 10, 5)
    await create_item_option("Cherry", "50 mg", 12, 0)
    return {n: (await get_item_info(n))["id"] for n in ("Cherry · 20 mg", "Cherry · 50 mg")}


class TestSelectorMarks:

    async def test_sold_out_option_is_marked_and_in_stock_one_is_not(self, make_callback_query, fsm_context):
        ids = await _family()
        call = make_callback_query(data="x")
        await shop._render_item_page(call, fsm_context, "Cherry · 20 mg", "gp_0", user_id=1)
        buttons = dict((cb, text) for text, cb in _flat(call.message.edit_text.call_args[1]["reply_markup"]))
        assert buttons[f"opt:{ids['Cherry · 20 mg']}"] == "✅ 20 mg"
        assert buttons[f"opt:{ids['Cherry · 50 mg']}"] == "50 mg ✕"

    async def test_sold_out_option_offers_notify_me(self, make_callback_query, fsm_context):
        await _family()
        call = make_callback_query(data="x")
        await shop._render_item_page(call, fsm_context, "Cherry · 50 mg", "gp_0", user_id=1)
        cbs = [cb for _t, cb in _flat(call.message.edit_text.call_args[1]["reply_markup"])]
        assert "sub_stock" in cbs and "add_to_cart" not in cbs


class TestNotice:

    async def test_restocked_option_notifies_its_own_subscribers_with_an_open_button(
            self, mock_bot, user_factory):
        ids = await _family()
        await user_factory(telegram_id=981001)
        await user_factory(telegram_id=981002)
        assert (await subscribe_to_stock(981001, "Cherry · 50 mg"))[0]
        assert (await subscribe_to_stock(981002, "Cherry · 20 mg"))[0]

        assert await notify_restock(mock_bot, "Cherry · 50 mg") == 1

        kwargs = mock_bot.send_message.await_args.kwargs
        assert kwargs["chat_id"] == 981001
        cbs = [cb for _t, cb in _flat(kwargs["reply_markup"])]
        assert cbs == [f"restock_open:{ids['Cherry · 50 mg']}", "close"]
        assert await is_subscribed_to_stock(981001, "Cherry · 50 mg") is False
        assert await is_subscribed_to_stock(981002, "Cherry · 20 mg") is True       # other option untouched


class TestOpenFromNotice:

    async def test_opens_the_product_card(self, make_callback_query, fsm_context, monkeypatch):
        ids = await _family()
        opened = AsyncMock()
        monkeypatch.setattr(shop, "_open_item", opened)
        call = make_callback_query(data=f"restock_open:{ids['Cherry · 50 mg']}")
        await restock_open_handler(call, fsm_context)
        assert opened.await_args.args[2:] == ("Cherry · 50 mg", "shop")

    async def test_unknown_or_broken_id_is_refused(self, make_callback_query, fsm_context, monkeypatch):
        opened = AsyncMock()
        monkeypatch.setattr(shop, "_open_item", opened)
        for data in ("restock_open:999999", "restock_open:abc"):
            call = make_callback_query(data=data)
            await restock_open_handler(call, fsm_context)
            assert call.answer.call_args[1].get("show_alert") is True
        opened.assert_not_awaited()


def test_the_open_button_text_is_registered_in_every_language():
    from bot.i18n.strings import TRANSLATIONS
    for lang in ("en", "ru", "ro"):
        assert TRANSLATIONS[lang]["btn.restock_open"].strip()
