"""Profile → My details, the profile text, and "use saved" at checkout."""
import httpx
import pytest
from sqlalchemy import select

from bot.database.main import Database
from bot.database.methods.create import add_to_cart
from bot.database.methods.orders import create_order_transaction
from bot.database.methods.profiles import save_details, saved_address
from bot.database.methods.read import check_user
from bot.database.methods.web_users import create_web_user
from bot.database.models.main import User, WebRole
from bot.handlers.user.checkout import (
    address_from_profile_handler, cart_checkout_handler, fulfillment_chosen_handler, name_from_profile_handler,
    name_from_telegram_handler, name_text_handler,
)
from bot.handlers.user.main import show_profile
from bot.handlers.user.profile_details import (
    clear_detail_handler, detail_text_handler, edit_detail_handler, my_details_handler,
)
from bot.keyboards.inline import profile_keyboard
from bot.states import CheckoutFSM, ProfileFSM
from bot.web.admin import UserAdmin, create_admin_app
from bot.web.language import LANG_COOKIE

UID = 940001


async def row(uid=UID):
    async with Database().session() as s:
        return (await s.execute(select(User).where(User.telegram_id == uid))).scalars().one()


def _cbs(mock):
    return [b.callback_data for r in mock.edit_text.call_args[1]["reply_markup"].inline_keyboard for b in r]


class TestStorage:

    async def test_save_clear_and_limits(self, user_factory):
        await user_factory(telegram_id=UID)
        assert await save_details(UID, contact_name=" Ana Popescu ", city="Chisinau", phone="+37369111222",
                                  address="Str. Mare 5")
        u = await row()
        assert (u.contact_name, u.city, u.phone, u.address) == ("Ana Popescu", "Chisinau", "+37369111222", "Str. Mare 5")
        await save_details(UID, city=None, address="   ")
        u = await row()
        assert u.city is None and u.address is None and u.contact_name == "Ana Popescu"
        await save_details(UID, contact_name="N" * 300)
        assert len((await row()).contact_name) == 100

    async def test_unknown_field_and_unknown_user(self, user_factory):
        with pytest.raises(ValueError):
            await save_details(UID, balance=5)
        assert await save_details(999999999, city="x") is False

    def test_saved_address_joins_city_and_address(self):
        assert saved_address({"city": "Chisinau", "address": "Str. 1"}) == "Chisinau, Str. 1"
        assert saved_address({"city": "", "address": "Str. 1"}) == "Str. 1"
        assert saved_address({"city": "Balti"}) == "Balti"
        assert saved_address(None) == ""


class TestProfileScreen:

    def test_profile_keyboard_has_details_and_no_operation_history(self):
        cbs = [b.callback_data for r in profile_keyboard(0, 1, 2).inline_keyboard for b in r]
        assert "my_details" in cbs and "favorites" in cbs
        assert "operation_history" not in cbs

    async def test_profile_text_lists_only_what_is_set(self, user_factory, make_callback_query):
        await user_factory(telegram_id=UID)
        call = make_callback_query(data="profile", user_id=UID)
        await show_profile(call)
        text = call.message.edit_text.call_args[0][0]
        assert "profile.name" not in text and "profile.city" not in text

        await save_details(UID, contact_name="Ana <b>", phone="+37369111222", city="Chisinau", address="Str. 1")
        from bot.database.methods.read import invalidate_user_cache
        await invalidate_user_cache(UID)
        call = make_callback_query(data="profile", user_id=UID)
        await show_profile(call)
        text = call.message.edit_text.call_args[0][0]
        for key in ("profile.name", "profile.phone", "profile.city", "profile.address"):
            assert key in text
        assert "Ana &lt;b&gt;" in text                       # escaped


class TestMyDetails:

    async def test_screen_lists_the_four_fields(self, user_factory, make_callback_query, fsm_context):
        await user_factory(telegram_id=UID)
        call = make_callback_query(data="my_details", user_id=UID)
        await my_details_handler(call, fsm_context)
        cbs = _cbs(call.message)
        assert [c for c in cbs if c.startswith("mydet_edit:")] == [
            "mydet_edit:name", "mydet_edit:phone", "mydet_edit:city", "mydet_edit:address"]
        assert "profile" in cbs

    @pytest.mark.parametrize("short,typed,column,expected", [
        ("name", "  Ana Popescu ", "contact_name", "Ana Popescu"),
        ("phone", "+373 69 111 222", "phone", "+373 69 111 222"),
        ("city", "Chisinau", "city", "Chisinau"),
        ("address", "Str. Mare 5, ap. 3", "address", "Str. Mare 5, ap. 3"),
    ])
    async def test_edit_each_field(self, user_factory, make_callback_query, make_message, fsm_context,
                                   short, typed, column, expected):
        await user_factory(telegram_id=UID)
        call = make_callback_query(data=f"mydet_edit:{short}", user_id=UID)
        await edit_detail_handler(call, fsm_context)
        assert await fsm_context.get_state() == ProfileFSM.editing
        assert f"details.ask_{short}" in call.message.edit_text.call_args[0][0]

        msg = make_message(text=typed, user_id=UID)
        await detail_text_handler(msg, fsm_context)
        assert getattr(await row(), column) == expected
        assert await fsm_context.get_state() is None
        assert "details.saved" in msg.answer.call_args[0][0]

    @pytest.mark.parametrize("short,typed", [("name", "x" * 150), ("phone", "abc"), ("city", ""), ("address", "y" * 600)])
    async def test_invalid_input_keeps_the_prompt(self, user_factory, make_callback_query, make_message, fsm_context,
                                                  short, typed):
        await user_factory(telegram_id=UID)
        await edit_detail_handler(make_callback_query(data=f"mydet_edit:{short}", user_id=UID), fsm_context)
        msg = make_message(text=typed, user_id=UID)
        await detail_text_handler(msg, fsm_context)
        assert await fsm_context.get_state() == ProfileFSM.editing
        assert (await check_user(UID)).get({"name": "contact_name"}.get(short, short)) is None

    async def test_clear_and_unknown_field(self, user_factory, make_callback_query, fsm_context):
        await user_factory(telegram_id=UID)
        await save_details(UID, city="Balti")
        call = make_callback_query(data="mydet_clear:city", user_id=UID)
        await clear_detail_handler(call, fsm_context)
        assert (await row()).city is None
        bad = make_callback_query(data="mydet_edit:zzz", user_id=UID)
        await edit_detail_handler(bad, fsm_context)
        assert bad.answer.call_args[1].get("show_alert") is True


class TestCheckoutPrefill:

    async def _start(self, make_callback_query, fsm_context, user_factory, item_factory, **details):
        await user_factory(telegram_id=UID)
        await save_details(UID, **details)
        from bot.database.methods.read import invalidate_user_cache
        await invalidate_user_cache(UID)
        await item_factory(name="PrefillItem", price=50, stock=5)
        await add_to_cart(UID, "PrefillItem")
        await cart_checkout_handler(make_callback_query(data="cart_checkout", user_id=UID), fsm_context)
        call = make_callback_query(data="co_ful:delivery", user_id=UID)
        await fulfillment_chosen_handler(call, fsm_context)
        return call

    async def test_saved_name_is_offered_and_used(self, make_callback_query, make_message, fsm_context,
                                                  user_factory, item_factory):
        call = await self._start(make_callback_query, fsm_context, user_factory, item_factory,
                                 contact_name="Ana Popescu", phone="+37369111222", city="Chisinau", address="Str. 1")
        assert "co_name_saved" in _cbs(call.message)
        use = make_callback_query(data="co_name_saved", user_id=UID)
        await name_from_profile_handler(use, fsm_context)
        assert (await fsm_context.get_data())["co_name"] == "Ana Popescu"
        assert await fsm_context.get_state() == CheckoutFSM.waiting_phone
        # the saved phone is offered as a keyboard button (a tap sends it as text)
        markup = use.message.answer.call_args[1]["reply_markup"]
        assert "+37369111222" in [b.text for r in markup.keyboard for b in r]

    async def test_saved_address_is_offered_and_used(self, make_callback_query, make_message, fsm_context,
                                                     user_factory, item_factory):
        await self._start(make_callback_query, fsm_context, user_factory, item_factory,
                          contact_name="Ana", phone="+37369111222", city="Chisinau", address="Str. 1")
        await fsm_context.set_state(CheckoutFSM.waiting_address)
        call = make_callback_query(data="co_addr_saved", user_id=UID)
        await address_from_profile_handler(call, fsm_context)
        assert (await fsm_context.get_data())["co_address"] == "Chisinau, Str. 1"
        assert await fsm_context.get_state() == CheckoutFSM.waiting_comment

    async def test_nothing_saved_nothing_offered(self, make_callback_query, fsm_context, user_factory, item_factory):
        call = await self._start(make_callback_query, fsm_context, user_factory, item_factory)
        assert "co_name_saved" not in _cbs(call.message)

    async def test_saved_buttons_without_a_saved_value_are_refused(self, make_callback_query, fsm_context,
                                                                   user_factory, item_factory):
        await self._start(make_callback_query, fsm_context, user_factory, item_factory)
        await fsm_context.set_state(CheckoutFSM.waiting_name)
        call = make_callback_query(data="co_name_saved", user_id=UID)
        await name_from_profile_handler(call, fsm_context)
        assert call.answer.call_args[1].get("show_alert") is True
        await fsm_context.set_state(CheckoutFSM.waiting_address)
        call = make_callback_query(data="co_addr_saved", user_id=UID)
        await address_from_profile_handler(call, fsm_context)
        assert call.answer.call_args[1].get("show_alert") is True

    async def test_order_saves_name_and_keeps_city_and_address_apart(self, user_factory, item_factory):
        await user_factory(telegram_id=UID)
        await save_details(UID, city="Chisinau", address="Str. 1")
        await item_factory(name="KeepApart", price=50, stock=9)
        await add_to_cart(UID, "KeepApart")
        ok, code, _ = await create_order_transaction(
            UID, fulfillment="delivery", customer_name="Ion Popa", phone="+37369000000",
            address="Chisinau, Str. 1", comment=None, payment_method="cod")
        assert ok, code
        u = await row()
        assert (u.contact_name, u.phone, u.city, u.address) == ("Ion Popa", "+37369000000", "Chisinau", "Str. 1")
        # a different typed address replaces the saved one
        await add_to_cart(UID, "KeepApart")
        ok, code, _ = await create_order_transaction(
            UID, fulfillment="delivery", customer_name="Ion Popa", phone="+37369000000",
            address="Balti, Str. 9", comment=None, payment_method="cod")
        assert ok, code
        assert (await row()).address == "Balti, Str. 9"


BOSS = ("detboss", "boss-pass-1")


class TestWebClients:

    async def test_list_search_and_edit_show_the_new_fields(self, user_factory):
        await user_factory(telegram_id=UID)
        await save_details(UID, contact_name="Ana Delivery", city="Orhei")
        await create_web_user(*BOSS, WebRole.ADMIN)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_admin_app(), client=("127.0.0.1", 5000)),
                                     base_url="http://testserver") as c:
            await c.post("/admin/login", data={"username": BOSS[0], "password": BOSS[1]})
            c.cookies.set(LANG_COOKIE, "en")
            page = (await c.get(f"/admin/{UserAdmin.identity}/list")).text
            assert "Ana Delivery" in page and "Orhei" in page and "Name for delivery" in page
            found = (await c.get(f"/admin/{UserAdmin.identity}/list?search=orhei")).text
            assert "Ana Delivery" in found
            details = (await c.get(f"/admin/{UserAdmin.identity}/details/{UID}")).text
            assert "Orhei" in details
            resp = await c.post(f"/admin/{UserAdmin.identity}/edit/{UID}", data={
                "role": "1", "balance": "0", "contact_name": "Ana D.", "city": "Soroca"})
            assert resp.status_code == 302, resp.text[:300]
            assert (await row()).city == "Soroca"
            c.cookies.set(LANG_COOKIE, "ru")
            assert "Имя для доставки" in (await c.get(f"/admin/{UserAdmin.identity}/list")).text
