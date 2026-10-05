"""Weight options on the admin side: the bot flow, the web panel form checks, delete and the list column."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from bot.database.main import Database
from bot.database.methods.create import create_category, create_item, create_item_option
from bot.database.methods.read import get_item_family, get_item_info
from bot.database.methods.update import set_item_stock
from bot.database.models.main import Goods
from bot.handlers.admin.adding_position import (
    add_option_callback_handler, add_option_head, add_option_label, add_option_price, add_option_stock,
)
from bot.handlers.admin.goods_management import (
    delete_str_item, show_item_stock, apply_stock_change, stock_action_callback_handler,
)
from bot.states import AddOptionFSM, GoodsFSM, StockFSM
from bot.web.admin import GoodsAdmin

pytestmark = pytest.mark.usefixtures("english")

_CAT = "OptAdminCat"


async def _head(name="OptHead", options=(), translations=None):
    await create_category(_CAT)
    await create_item(name, "Fruity", 0, _CAT, names=translations)
    for label, price, stock in options:
        assert await create_item_option(name, label, price, stock) == (True, "success")


def _texts(msg):
    return [c.args[0] for c in msg.answer.await_args_list]


async def _walk(make_message, fsm_context, head, label, price="90", stock="5"):
    msg = None
    for handler, text in ((add_option_head, head), (add_option_label, label),
                          (add_option_price, price), (add_option_stock, stock)):
        msg = make_message(text=text, user_id=1)
        await handler(msg, fsm_context)
    return msg


class TestAddOptionFlow:

    async def test_start_sets_the_head_state(self, make_callback_query, fsm_context):
        call = make_callback_query(data="add_option", user_id=1)
        await add_option_callback_handler(call, fsm_context)
        assert await fsm_context.get_state() == AddOptionFSM.waiting_head
        call.message.edit_text.assert_called_once()

    async def test_full_walk_creates_the_option_and_audits(self, make_message, fsm_context):
        await _head("OptWalk")
        with patch('bot.handlers.admin.adding_position.log_audit', new_callable=AsyncMock) as audit, \
                patch('bot.handlers.admin.adding_position._notify_restock_safe', new_callable=AsyncMock) as notify, \
                patch('bot.handlers.admin.adding_position.announce_arrival', new_callable=AsyncMock) as announce:
            msg = await _walk(make_message, fsm_context, "OptWalk", "50 g", "90", "5")

        opt = await get_item_info("OptWalk · 50 g")
        assert opt["price"] == 90 and opt["stock"] == 5 and opt["variant_label"] == "50 g"
        assert "OptWalk · 50 g" in _texts(msg)[-1]
        assert await fsm_context.get_state() is None
        assert audit.await_args[0][0] == "create_item_option"
        assert audit.await_args[1]["resource_id"] == "OptWalk · 50 g"
        notify.assert_awaited_once()
        announce.assert_awaited_once()

    async def test_head_typed_in_another_language(self, make_message, fsm_context):
        await _head("OptTr", translations={"ro": "Optiune ro", "en": "OptTr en"})
        msg = make_message(text="optiune RO", user_id=1)
        await add_option_head(msg, fsm_context)
        assert (await fsm_context.get_data())["option_head"] == "OptTr"
        assert await fsm_context.get_state() == AddOptionFSM.waiting_label

    async def test_unknown_head_is_refused(self, make_message, fsm_context):
        await fsm_context.set_state(AddOptionFSM.waiting_head)
        msg = make_message(text="No such product", user_id=1)
        await add_option_head(msg, fsm_context)
        assert await fsm_context.get_state() == AddOptionFSM.waiting_head
        assert _texts(msg)[0] == "admin.goods.option.head_not_found"

    async def test_an_option_is_refused_as_head(self, make_message, fsm_context):
        await _head("OptNoNest", [("50 g", 10, 1)])
        await fsm_context.set_state(AddOptionFSM.waiting_head)
        msg = make_message(text="OptNoNest · 50 g", user_id=1)
        await add_option_head(msg, fsm_context)
        assert await fsm_context.get_state() == AddOptionFSM.waiting_head
        assert _texts(msg)[0] == "admin.goods.option.head_is_option"

    @pytest.mark.parametrize("label", ["a · b", "x" * 33, "   "])
    async def test_bad_label_is_reprompted(self, make_message, fsm_context, label):
        await fsm_context.set_state(AddOptionFSM.waiting_label)
        msg = make_message(text=label, user_id=1)
        await add_option_label(msg, fsm_context)
        assert await fsm_context.get_state() == AddOptionFSM.waiting_label
        assert _texts(msg)[0] == "admin.goods.option.label.invalid"

    async def test_bad_price_and_stock_are_reprompted(self, make_message, fsm_context):
        await fsm_context.set_state(AddOptionFSM.waiting_price)
        await add_option_price(make_message(text="abc", user_id=1), fsm_context)
        assert await fsm_context.get_state() == AddOptionFSM.waiting_price
        await fsm_context.set_state(AddOptionFSM.waiting_stock)
        await add_option_stock(make_message(text="-1", user_id=1), fsm_context)
        assert await fsm_context.get_state() == AddOptionFSM.waiting_stock

    async def test_duplicate_label_reports_and_ends(self, make_message, fsm_context):
        await _head("OptDup", [("50 g", 10, 1)])
        msg = await _walk(make_message, fsm_context, "OptDup", "50 G")
        assert _texts(msg)[-1] == "admin.goods.option.exists"
        assert await fsm_context.get_state() is None
        assert len((await get_item_family("OptDup"))["options"]) == 1

    async def test_zero_stock_does_not_announce(self, make_message, fsm_context):
        await _head("OptZero")
        with patch('bot.handlers.admin.adding_position._notify_restock_safe', new_callable=AsyncMock) as notify:
            await _walk(make_message, fsm_context, "OptZero", "1 kg", "300", "0")
        notify.assert_not_awaited()
        assert (await get_item_info("OptZero · 1 kg"))["stock"] == 0

    def test_handlers_need_catalog_permission(self):
        from bot.handlers.admin import adding_position as ap
        from bot.database.models import Permission
        handlers = [r for r in ap.router.message.handlers + ap.router.callback_query.handlers
                    if r.callback.__name__.startswith("add_option")]
        assert len(handlers) == 5
        for r in handlers:
            assert any(getattr(f.callback, "permission", None) == Permission.CATALOG_MANAGE for f in r.filters)


class TestOptionsAreEditedByTheirName:

    async def test_stock_card_of_an_option_by_composite_and_translated_name(self, make_message, fsm_context):
        await _head("OptEd", [("50 g", 10, 1)], translations={"ro": "OptEd ro"})
        await fsm_context.set_state(StockFSM.waiting_item_name)
        for typed in ("OptEd · 50 g", "opted ro · 50 g"):
            msg = make_message(text=typed, user_id=1)
            await show_item_stock(msg, fsm_context)
            assert (await fsm_context.get_data())["stock_item_name"] == "OptEd · 50 g"
            await fsm_context.set_state(StockFSM.waiting_item_name)

    async def test_stock_set_on_an_option_leaves_the_head_alone(self, make_message, make_callback_query, fsm_context):
        await _head("OptStock", [("50 g", 10, 1)])
        await set_item_stock("OptStock", 7)
        await fsm_context.set_state(StockFSM.waiting_item_name)
        await show_item_stock(make_message(text="OptStock · 50 g", user_id=1), fsm_context)
        await stock_action_callback_handler(make_callback_query(data="stock_set", user_id=1), fsm_context)
        with patch('bot.handlers.admin.goods_management.log_audit', new_callable=AsyncMock), \
                patch('bot.handlers.admin.goods_management._notify_restock_safe', new_callable=AsyncMock), \
                patch('bot.handlers.admin.goods_management.announce_arrival', new_callable=AsyncMock):
            await apply_stock_change(make_message(text="9", user_id=1), fsm_context)
        assert (await get_item_info("OptStock · 50 g"))["stock"] == 9
        assert (await get_item_info("OptStock"))["stock"] == 7

    async def test_head_card_lists_the_options(self, make_message, fsm_context):
        await _head("OptCard", [("50 g", 90, 5), ("200 g", 300, 2)])
        await fsm_context.set_state(StockFSM.waiting_item_name)
        msg = make_message(text="OptCard", user_id=1)
        await show_item_stock(msg, fsm_context)
        card = msg.answer.await_args.args[0]
        assert "50 g" in card and "200 g" in card and "90" in card and "300" in card

    async def test_option_card_and_standalone_card_have_no_options_block(self, make_message, fsm_context, item_factory):
        await _head("OptCard2", [("50 g", 90, 5)])
        await item_factory(name="OptPlain")
        for name in ("OptCard2 · 50 g", "OptPlain"):
            await fsm_context.set_state(StockFSM.waiting_item_name)
            msg = make_message(text=name, user_id=1)
            await show_item_stock(msg, fsm_context)
            assert "🧩" not in msg.answer.await_args.args[0]


class TestDeleteHeadFromTheBot:

    async def test_delete_removes_options_and_says_so(self, make_message, fsm_context):
        await _head("OptDelBot", [("50 g", 10, 1), ("200 g", 30, 1)])
        await fsm_context.set_state(GoodsFSM.waiting_item_name_delete)
        msg = make_message(text="OptDelBot", user_id=1)
        with patch('bot.handlers.admin.goods_management.log_audit', new_callable=AsyncMock) as audit:
            await delete_str_item(msg, fsm_context)
        assert await get_item_info("OptDelBot · 50 g") is None
        assert await get_item_info("OptDelBot") is None
        assert _texts(msg)[0] == "admin.goods.delete.position.success_options:{'count': 2}"
        assert "options=2" in audit.await_args[1]["details"]

    async def test_delete_of_one_option_keeps_the_head(self, make_message, fsm_context):
        await _head("OptDelOne", [("50 g", 10, 1), ("200 g", 30, 1)])
        await fsm_context.set_state(GoodsFSM.waiting_item_name_delete)
        msg = make_message(text="OptDelOne · 50 g", user_id=1)
        with patch('bot.handlers.admin.goods_management.log_audit', new_callable=AsyncMock):
            await delete_str_item(msg, fsm_context)
        fam = await get_item_family("OptDelOne")
        assert [o["variant_label"] for o in fam["options"]] == ["200 g"]


# --- web panel ---------------------------------------------------------------------------------

def _request():
    request = MagicMock()
    request.client.host = "127.0.0.1"
    request.state = MagicMock()
    return request


async def _goods(name):
    async with Database().session() as s:
        return (await s.execute(select(Goods).where(Goods.name == name))).scalars().first()


async def _category_id():
    async with Database().session() as s:
        from bot.database.models.main import Categories
        return (await s.execute(select(Categories.id).where(Categories.name == _CAT))).scalar()


def _form(name, head_id=None, label=None, **extra):
    data = {"name": name, **{f"description_{l}": "d" for l in ("en", "ru", "ro")}}
    data.update({"price": 5, "stock": 1, "variant_of": head_id, "variant_label": label, **extra})
    return data


async def _change(data, model=None, is_created=True):
    view = GoodsAdmin()
    model = model if model is not None else Goods()
    with patch('bot.web.admin.safe_create_task', side_effect=lambda c: c.close()):
        await view.on_model_change(data, model, is_created, _request())
    return data


async def _save(data):
    """What SQLAdmin does after on_model_change for a new product: store the columns."""
    cols = {c.name for c in Goods.__table__.columns}
    row = {k: v for k, v in data.items() if k in cols}
    row["category_id"] = int(data["category"]) if data.get("category") else await _category_id()
    async with Database().session() as s:
        s.add(Goods(**row))


class TestWebFormValidation:

    async def test_option_is_named_after_head_and_takes_its_category(self):
        await _head("WebHead", translations={"ro": "WebHead ro"})
        head = await _goods("WebHead")
        data = await _change(_form("whatever typed", head.id, " 50 g "))
        assert data["name"] == "WebHead · 50 g"
        assert data["variant_label"] == "50 g" and data["variant_of"] == head.id
        assert data["category"] == str(head.category_id)
        assert data["name_ro"] == "WebHead ro · 50 g"
        assert data["description"] == "" and data["description_en"] is None
        await _save(data)
        fam = await get_item_family("WebHead")
        assert [o["name"] for o in fam["options"]] == ["WebHead · 50 g"]

    async def test_standalone_product_is_untouched(self):
        await _head("WebSolo")
        data = await _change(_form("WebSolo2"))
        assert data["name"] == "WebSolo2" and data["variant_of"] is None and data["variant_label"] is None
        assert "category" not in data

    @pytest.mark.parametrize("variant_of,label,error", [
        (999999, "50 g", "does not exist"),
        (None, "50 g", "only be set together"),
    ])
    async def test_refusals_without_a_valid_head(self, variant_of, label, error):
        with pytest.raises(ValueError, match=error):
            await _change(_form("X", variant_of, label))

    async def test_head_cannot_be_an_option(self):
        await _head("WebNest", [("50 g", 10, 1)])
        opt = await _goods("WebNest · 50 g")
        with pytest.raises(ValueError, match="cannot itself be an option"):
            await _change(_form("X", opt.id, "10 g"))

    @pytest.mark.parametrize("label,error", [
        (None, "Enter the option label"), ("  ", "Enter the option label"),
        ("a · b", "must not contain"), ("x" * 33, "too long"),
    ])
    async def test_label_rules(self, label, error):
        await _head("WebLabel")
        head = await _goods("WebLabel")
        with pytest.raises(ValueError, match=error):
            await _change(_form("X", head.id, label))

    async def test_label_unique_per_head_case_insensitive(self):
        await _head("WebUniq", [("50 g", 10, 1)])
        head = await _goods("WebUniq")
        with pytest.raises(ValueError, match="already has an option"):
            await _change(_form("X", head.id, "50 G"))
        await _head("WebUniq2")
        other = await _goods("WebUniq2")
        await _change(_form("X", other.id, "50 g"))          # same label under another head is fine

    async def test_editing_an_option_keeps_its_own_label(self):
        await _head("WebSelf", [("50 g", 10, 1)])
        head, opt = await _goods("WebSelf"), await _goods("WebSelf · 50 g")
        data = await _change(_form("x", head.id, "50 g"), opt, is_created=False)
        assert data["name"] == "WebSelf · 50 g"

    async def test_product_with_options_cannot_become_an_option(self):
        await _head("WebBusy", [("50 g", 10, 1)])
        await _head("WebTarget")
        busy, target = await _goods("WebBusy"), await _goods("WebTarget")
        with pytest.raises(ValueError, match="has options"):
            await _change(_form("WebBusy", target.id, "1 kg"), busy, is_created=False)
        with pytest.raises(ValueError, match="of itself"):
            await _change(_form("WebBusy", busy.id, "1 kg"), busy, is_created=False)

    async def test_clearing_the_head_makes_it_standalone(self):
        await _head("WebFree", [("50 g", 10, 1)])
        opt = await _goods("WebFree · 50 g")
        data = await _change(_form("WebFree · 50 g"), opt, is_created=False)
        assert data["variant_of"] is None and data["variant_label"] is None

    async def test_head_rename_leaves_options_alone(self):
        await _head("WebRen", [("50 g", 10, 1)])
        head = await _goods("WebRen")
        await _change(_form("WebRen renamed"), head, is_created=False)
        assert (await _goods("WebRen · 50 g")) is not None

    async def test_moving_a_head_moves_its_options(self):
        await _head("WebMove", [("50 g", 10, 1)])
        await create_category("OptAdminCat2")
        head = await _goods("WebMove")
        async with Database().session() as s:
            from bot.database.models.main import Categories
            cat2 = (await s.execute(select(Categories.id).where(Categories.name == "OptAdminCat2"))).scalar()
        request = _request()
        request.state.item_old_category_id = head.category_id
        head.category_id = cat2
        with patch('bot.web.admin.safe_create_task', side_effect=lambda c: c.close()):
            await GoodsAdmin()._follow_head_category(head, request.state.item_old_category_id)
        assert (await _goods("WebMove · 50 g")).category_id == cat2


class TestWebDeleteAndList:

    async def test_deleting_a_head_deletes_its_options_and_drops_caches(self, fake_cache):
        await _head("WebDel", [("50 g", 10, 1), ("200 g", 30, 1)])
        head = await _goods("WebDel")
        fake_cache.store["item_info:WebDel · 50 g"] = {"name": "x"}
        view = GoodsAdmin()
        await view.on_model_delete(head, _request())
        async with Database().session() as s:
            await s.delete(await s.get(Goods, head.id))
        await view.after_model_delete(head, _request())
        assert await _goods("WebDel") is None
        assert await _goods("WebDel · 50 g") is None and await _goods("WebDel · 200 g") is None
        assert "item_info:WebDel · 50 g" not in fake_cache.store

    async def test_deleting_an_option_leaves_the_head(self):
        await _head("WebDelOpt", [("50 g", 10, 1)])
        opt = await _goods("WebDelOpt · 50 g")
        await GoodsAdmin().on_model_delete(opt, _request())
        assert await _goods("WebDelOpt") is not None

    async def test_list_has_an_options_column_and_hides_the_options_themselves(self):
        await _head("WebList", [("50 g", 10, 1)])
        view = GoodsAdmin()
        assert "options_summary" in view._list_prop_names
        assert view._column_labels["options_summary"] == "Options"
        head = await _goods("WebList")
        head.options_summary = "50 g: 10 / 1"
        assert (await view.get_list_value(head, "options_summary"))[1] == "50 g: 10 / 1"
        async with Database().session() as s:
            names = (await s.execute(view.list_query(None))).scalars().all()
        assert "WebList" in [g.name for g in names] and "WebList \u00b7 50 g" not in [g.name for g in names]

    async def test_form_has_the_label_field_and_head_select(self):
        view = GoodsAdmin()
        assert view._column_labels["variant_of"] == "Option of"
        assert view._column_labels["variant_label"] == "Option label"


async def _value(view, obj):
    value = await view.get_list_value(obj, "variant_label")
    return value[0] if isinstance(value, tuple) else value


class TestEditFlowRefusesOptions:

    async def test_generic_edit_refuses_an_option(self, make_message, fsm_context):
        from unittest.mock import AsyncMock
        from bot.database.methods.create import create_category, create_item, create_item_option
        from bot.handlers.admin import update_position as up
        await create_category("EditCat")
        await create_item("EditHead", "d", 1, "EditCat")
        await create_item_option("EditHead", "50 g", 5, 1)
        msg = make_message(text="EditHead · 50 g")
        state = fsm_context
        await up.check_item_name_for_update(msg, state)
        msg.answer.assert_awaited()
        assert "weight option" in msg.answer.await_args[0][0]
        assert await state.get_state() is None
