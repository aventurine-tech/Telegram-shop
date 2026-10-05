import asyncio
from decimal import Decimal
from functools import partial

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest
from pydantic import ValidationError

from bot.database.methods import (
    query_categories, get_item_info_cached, select_item_stock_cached, effective_price
)
from bot.database.methods.read import (
    get_item_avg_rating, has_purchased_item, validate_promo_for_item,
    get_user_review, invalidate_rating_cache, is_subscribed_to_stock,
)
from bot.database.methods.orders import get_order, cancel_order_transaction
from bot.database.methods.pricing import apply_promo_discount
from bot.database.methods.create import create_review, subscribe_to_stock
from bot.database.methods.delete import unsubscribe_from_stock
from bot.database.methods.lazy_queries import (
    query_item_reviews, query_goods_search, query_items_in_category, query_user_orders,
)
from bot.database.methods.transactions import redeem_balance_promo
from bot.database.methods.audit import log_audit_bg
from bot.database.methods.cache_utils import safe_create_task
from bot.keyboards import item_info, back, lazy_paginated_keyboard, order_keyboard
from bot.keyboards.inline import simple_buttons, rating_keyboard
from aiogram.types import InlineKeyboardButton
from bot.i18n import localize, esc
from bot.misc import EnvKeys, LazyPaginator, ReviewRequest
from bot.misc.metrics import get_metrics
from bot.misc.services.order_view import format_order
from bot.misc.services.restock_notifier import notify_restock
from bot.states import ShopStates
from bot.states.review_state import ReviewFSM
from bot.states.promo_state import PromoFSM

router = Router()


def _browsing_state_for(back_data: str):
    """The FSM state the item card's Back button needs, or None if it needs none."""
    if back_data.startswith('gp_'):
        return ShopStates.viewing_goods
    if back_data.startswith('sp_'):
        return ShopStates.viewing_search_results
    return None


def _page_arg(raw: str) -> int | None:
    """Parse a page number out of callback_data. None if it is not a valid page."""
    try:
        page = int(raw)
    except (TypeError, ValueError):
        return None
    return page if page >= 0 else None


# --- Shared helper: render item page ---

async def _render_item_page(target, state: FSMContext, item_name: str, back_data: str = None, user_id: int = None):
    """
    Render the item detail page with optional promo discount.
    `target` can be CallbackQuery or Message.
    """
    data = await state.get_data()
    if not back_data:
        back_data = data.get('item_back_data', 'gp_0')

    item_info_data = await get_item_info_cached(item_name)
    if not item_info_data:
        if isinstance(target, CallbackQuery):
            await target.answer(localize("shop.item.not_found"), show_alert=True)
        else:
            await target.answer(localize("shop.item.not_found"))
        return

    required_state = _browsing_state_for(back_data)
    if required_state is not None:
        await state.set_state(required_state)

    reviews_enabled = EnvKeys.REVIEWS_ENABLED == "1"

    reads = [select_item_stock_cached(item_name)]
    if reviews_enabled:
        reads.append(get_item_avg_rating(item_name))
        reads.append(query_item_reviews(item_name, count_only=True))
        if user_id:
            reads.append(has_purchased_item(user_id, item_name))
    results = await asyncio.gather(*reads)

    stock = results[0]
    avg_rating = results[1] if reviews_enabled else None
    review_count_val = results[2] if reviews_enabled else 0
    purchased = results[3] if (reviews_enabled and user_id) else False

    out_of_stock = stock <= 0
    quantity_line = localize("shop.item.out_of_stock") if out_of_stock else localize("shop.item.in_stock", count=stock)
    subscribed = bool(
        out_of_stock and user_id and await is_subscribed_to_stock(user_id, item_name)
    )

    # Build price line. Sale price (if any) is the base; a promo stacks on top.
    sale_price, on_sale, original_price = effective_price(item_info_data)
    price = sale_price

    applied_promo = data.get('applied_promo')
    discounted = None
    if applied_promo and user_id:
        valid, _err, promo = await validate_promo_for_item(applied_promo, item_name, user_id)
        if valid:
            discounted = apply_promo_discount(
                price, promo['discount_type'], promo['discount_value'], 1
            )
        else:
            applied_promo = None
            await state.update_data(applied_promo=None)

    if discounted is not None:
        price_line = localize(
            "shop.item.price_discounted",
            original=original_price, discounted=discounted,
            currency=EnvKeys.PAY_CURRENCY, code=esc(applied_promo),
        )
    elif on_sale:
        percent = (Decimal(str(item_info_data.get("sale_percent") or 0))).quantize(Decimal("1"))
        price_line = localize(
            "shop.item.price_sale",
            original=original_price, sale=sale_price,
            currency=EnvKeys.PAY_CURRENCY, percent=percent,
        )
    else:
        price_line = localize("shop.item.price", amount=price, currency=EnvKeys.PAY_CURRENCY)

    markup = item_info(
        back_data,
        avg_rating=avg_rating, review_count=review_count_val,
        has_purchased=purchased, applied_promo=applied_promo,
        reviews_enabled=reviews_enabled,
        out_of_stock=out_of_stock, subscribed=subscribed,
    )

    text_lines = [
        localize("shop.item.title", name=esc(item_name)),
        localize("shop.item.description", description=esc(item_info_data["description"])),
        price_line,
        quantity_line,
    ]
    if reviews_enabled and avg_rating is not None:
        text_lines.append(localize("review.avg_rating", rating=avg_rating, count=review_count_val))

    text = "\n".join(text_lines)

    try:
        if hasattr(target, 'message') and hasattr(target.message, 'edit_text'):
            await target.message.edit_text(text, reply_markup=markup)
        else:
            await target.answer(text, reply_markup=markup)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise


# --- Shop / categories / items ---

async def _show_categories_page(call: CallbackQuery, state: FSMContext, page: int):
    """Render one page of the category list (shared by the shop entry + paginate handlers)."""
    paginator = LazyPaginator(query_categories, per_page=10)

    # Pre-fetch page items to build the index map used by the item_callback.
    page_items = await paginator.get_page(page)
    items_index = {cat: idx for idx, cat in enumerate(page_items)}

    markup = await lazy_paginated_keyboard(
        paginator=paginator,
        item_text=lambda cat: cat,
        item_callback=lambda cat: f"cat:{items_index[cat]}:{page}",
        page=page,
        back_cb="back_to_menu",
        nav_cb_prefix="categories-page_",
        extra_rows=[[InlineKeyboardButton(
            text=localize("btn.search"), callback_data="shop_search",
        )]],
    )

    await call.message.edit_text(localize("shop.categories.title"), reply_markup=markup)
    await state.update_data(
        category_page_items=list(page_items),
        category_page_num=page,
    )


@router.callback_query(F.data == "shop")
async def shop_callback_handler(call: CallbackQuery, state: FSMContext):
    """Show list of shop categories with lazy loading."""
    metrics = get_metrics()
    if metrics:
        metrics.track_conversion("purchase_funnel", "view_shop", call.from_user.id)

    await _show_categories_page(call, state, 0)
    await state.set_state(ShopStates.viewing_categories)


@router.callback_query(F.data.startswith('categories-page_'))
async def navigate_categories(call: CallbackQuery, state: FSMContext):
    """Pagination across shop categories with cache."""
    parts = call.data.split('_', 1)
    page = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    await _show_categories_page(call, state, page)


async def _show_goods_page(call: CallbackQuery, state: FSMContext,
                           category_name: str, cat_page: int, page: int):
    """Render one page of goods inside a category (shared by category-open + paginate)."""
    from bot.database.methods.lazy_queries import query_items_in_category

    paginator = LazyPaginator(partial(query_items_in_category, category_name), per_page=10)

    page_items = await paginator.get_page(page)
    items_index = {item: i for i, item in enumerate(page_items)}

    markup = await lazy_paginated_keyboard(
        paginator=paginator,
        item_text=lambda item: item,
        item_callback=lambda item: f"itm:{items_index[item]}:{page}",
        page=page,
        back_cb=f"categories-page_{cat_page}",
        nav_cb_prefix="gp_",
    )

    await call.message.edit_text(localize("shop.goods.choose"), reply_markup=markup)
    await state.update_data(
        current_category=category_name,
        goods_page_items=list(page_items),
        goods_page_num=page,
        categories_last_viewed_page=cat_page,
    )
    await state.set_state(ShopStates.viewing_goods)


@router.callback_query(F.data.startswith('cat:'))
async def items_list_callback_handler(call: CallbackQuery, state: FSMContext):
    """
    Show items of selected category.
    Parse index and page from cat:{index}:{page}, look up category name from state.
    """
    try:
        parts = call.data.split(':')
        idx = int(parts[1])
        cat_page = int(parts[2]) if len(parts) > 2 else 0
    except (ValueError, IndexError):
        await call.answer(localize("shop.item.not_found"), show_alert=True)
        return

    category = await _page_item_from_state(state, 'category_page_items', 'category_page_num', cat_page, idx)
    if category is None:
        category = await _page_item_at(query_categories, cat_page, idx)
    if category is None:
        await call.answer(localize("shop.item.not_found"), show_alert=True)
        return

    await _show_goods_page(call, state, category, cat_page, 0)


@router.callback_query(F.data.startswith('gp_'), ShopStates.viewing_goods)
async def navigate_goods(call: CallbackQuery, state: FSMContext):
    """
    Pagination for items inside selected category.
    Format: gp_{page}
    """
    page = _page_arg(call.data[3:])
    if page is None:
        await call.answer(localize("errors.pagination_invalid"), show_alert=True)
        return
    data = await state.get_data()
    await _show_goods_page(
        call, state,
        data.get('current_category', ''),
        data.get('categories_last_viewed_page', 0),
        page,
    )


async def _page_item_at(query_func, page: int, idx: int):
    """Return the item at ``idx`` on ``page`` of ``query_func``, or None."""
    paginator = LazyPaginator(query_func, per_page=10)
    page_items = await paginator.get_page(page)
    if idx < 0 or idx >= len(page_items):
        return None
    return page_items[idx]


async def _page_item_from_state(state: FSMContext, list_key: str, page_key: str,
                                page: int, idx: int):
    """Resolve idx->name from the page list saved by the last render.

    Avoids re-running the list query the user just saw. Returns None when the
    state doesn't cover this page (restart, stale keyboard) — the caller then
    falls back to _page_item_at.
    """
    data = await state.get_data()
    if data.get(page_key) != page:
        return None
    items = data.get(list_key)
    if not items or idx < 0 or idx >= len(items):
        return None
    return items[idx]


async def _open_item(call: CallbackQuery, state: FSMContext, item_name: str, back_data: str):
    """Open an item card and record it for the on-screen (csrf) item context."""
    metrics = get_metrics()
    if metrics:
        metrics.track_conversion("purchase_funnel", "view_item", call.from_user.id)

    # Save item name and back_data in state
    updates = {"csrf_item": item_name, "item_back_data": back_data}
    if (await state.get_data()).get('csrf_item') != item_name:
        updates["applied_promo"] = None
    await state.update_data(**updates)

    await _render_item_page(call, state, item_name, back_data, user_id=call.from_user.id)


@router.callback_query(F.data.startswith('itm:'))
async def item_info_callback_handler(call: CallbackQuery, state: FSMContext):
    """
    Show detailed information about the item.
    Format: itm:{index}:{page}
    """
    try:
        parts = call.data.split(':')
        idx = int(parts[1])
        goods_page = int(parts[2]) if len(parts) > 2 else 0
    except (ValueError, IndexError):
        await call.answer(localize("shop.item.not_found"), show_alert=True)
        return

    item_name = await _page_item_from_state(state, 'goods_page_items', 'goods_page_num', goods_page, idx)
    if not item_name:
        category = (await state.get_data()).get('current_category', '')
        item_name = await _page_item_at(partial(query_items_in_category, category), goods_page, idx)
    if not item_name:
        await call.answer(localize("shop.item.not_found"), show_alert=True)
        return
    await _open_item(call, state, item_name, f"gp_{goods_page}")


# --- Catalog search ---

async def _show_search_page(target, state: FSMContext, query: str, page: int):
    """Render one page of search results. `target` is a CallbackQuery or Message."""
    paginator = LazyPaginator(
        partial(query_goods_search, query), per_page=10,
    )

    page_items = await paginator.get_page(page)
    safe_query = esc(query)

    async def _render(text, markup):
        if isinstance(target, CallbackQuery):
            await target.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
        else:
            await target.answer(text, reply_markup=markup, parse_mode="HTML")

    if not page_items and page == 0:
        await _render(localize("shop.search.empty", query=safe_query), back("shop"))
        await state.set_state(None)
        return

    items_index = {item: i for i, item in enumerate(page_items)}
    markup = await lazy_paginated_keyboard(
        paginator=paginator,
        item_text=lambda item: item,
        item_callback=lambda item: f"sitm:{items_index[item]}:{page}",
        page=page,
        back_cb="shop",
        nav_cb_prefix="sp_",
    )

    total = await paginator.get_total_count()
    await _render(localize("shop.search.results", query=safe_query, count=total), markup)

    await state.update_data(
        search_query=query,
        search_page_items=list(page_items),
        search_page_num=page,
    )
    await state.set_state(ShopStates.viewing_search_results)


@router.callback_query(F.data == "shop_search")
async def shop_search_handler(call: CallbackQuery, state: FSMContext):
    """Prompt for a search query."""
    await call.message.edit_text(localize("shop.search.prompt"), reply_markup=back("shop"))
    await state.set_state(ShopStates.waiting_search_query)


@router.message(ShopStates.waiting_search_query, F.text)
async def receive_search_query_handler(message: Message, state: FSMContext):
    query = (message.text or "").strip()

    if len(query) < 2 or len(query) > 64:
        # Stay in the state so the user can just retype.
        await message.answer(localize("shop.search.too_short"), reply_markup=back("shop"))
        return

    await _show_search_page(message, state, query, 0)


@router.callback_query(F.data.startswith('sp_'), ShopStates.viewing_search_results)
async def navigate_search(call: CallbackQuery, state: FSMContext):
    """Pagination across search results. Format: sp_{page}"""
    page = _page_arg(call.data[3:])
    if page is None:
        await call.answer(localize("errors.pagination_invalid"), show_alert=True)
        return
    data = await state.get_data()
    await _show_search_page(call, state, data.get('search_query', ''), page)


@router.callback_query(F.data.startswith('sitm:'))
async def search_item_info_handler(call: CallbackQuery, state: FSMContext):
    """
    Open an item from the search results.
    Format: sitm:{index}:{page}

    A separate namespace from itm:/gp_ because navigate_goods re-derives its page
    from current_category, which search results do not have.
    """
    try:
        parts = call.data.split(':')
        idx = int(parts[1])
        page = int(parts[2]) if len(parts) > 2 else 0
    except (ValueError, IndexError):
        await call.answer(localize("shop.item.not_found"), show_alert=True)
        return

    item_name = await _page_item_from_state(state, 'search_page_items', 'search_page_num', page, idx)
    if not item_name:
        query = (await state.get_data()).get('search_query', '')
        item_name = await _page_item_at(partial(query_goods_search, query), page, idx)
    if not item_name:
        await call.answer(localize("shop.item.not_found"), show_alert=True)
        return
    await _open_item(call, state, item_name, f"sp_{page}")


# --- Restock notifications ---

@router.callback_query(F.data == "sub_stock")
async def subscribe_stock_handler(call: CallbackQuery, state: FSMContext):
    """Subscribe to the restock notification for the item on screen."""
    item_name = (await state.get_data()).get('csrf_item')
    if not item_name:
        await call.answer(localize("shop.item.not_found"), show_alert=True)
        return

    ok, _code = await subscribe_to_stock(call.from_user.id, item_name)
    await call.answer(localize("stock.subscribed" if ok else "errors.something_wrong"))
    await _render_item_page(call, state, item_name, user_id=call.from_user.id)


@router.callback_query(F.data == "unsub_stock")
async def unsubscribe_stock_handler(call: CallbackQuery, state: FSMContext):
    """Cancel the restock notification for the item on screen."""
    item_name = (await state.get_data()).get('csrf_item')
    if not item_name:
        await call.answer(localize("shop.item.not_found"), show_alert=True)
        return

    await unsubscribe_from_stock(call.from_user.id, item_name)
    await call.answer(localize("stock.unsubscribed"))
    await _render_item_page(call, state, item_name, user_id=call.from_user.id)


# --- Promo Code Application ---

async def _leave_promo_input(state: FSMContext) -> None:
    """Put back the browsing state that the promo prompt replaced."""
    pre_state = (await state.get_data()).get('pre_promo_state')
    if not pre_state:
        return
    await state.update_data(pre_promo_state=None)
    await state.set_state(pre_state)


@router.callback_query(F.data == "apply_promo")
async def apply_promo_handler(call: CallbackQuery, state: FSMContext):
    await call.message.edit_text(localize("promo.enter_code"), reply_markup=back("back_to_item"))
    await state.update_data(pre_promo_state=await state.get_state())
    await state.set_state(PromoFSM.waiting_item_code)


@router.message(PromoFSM.waiting_item_code, F.text)
async def promo_code_text_handler(message: Message, state: FSMContext):
    """Apply a promo code typed on an item page."""
    data = await state.get_data()
    item_name = data.get('csrf_item')

    await _leave_promo_input(state)

    if not item_name:
        await message.answer(localize("shop.item.not_found"), reply_markup=back("back_to_menu"))
        return

    code = (message.text or "").strip().upper()
    valid, error_key, promo_data = await validate_promo_for_item(code, item_name, message.from_user.id)

    if not valid:
        await message.answer(localize(error_key), reply_markup=back("back_to_item"))
        return

    # Only the code is kept. The discount itself is re-derived on every render from the live promo row, so a code that stops applying stops showing.
    await state.update_data(applied_promo=code)

    # Re-render item page with discounted price
    await _render_item_page(message, state, item_name, user_id=message.from_user.id)


@router.callback_query(F.data == "remove_promo")
async def remove_promo_handler(call: CallbackQuery, state: FSMContext):
    await state.update_data(applied_promo=None)
    data = await state.get_data()
    item_name = data.get('csrf_item')
    if item_name:
        await _render_item_page(call, state, item_name, user_id=call.from_user.id)
    else:
        await call.answer(localize("promo.removed"))


@router.callback_query(F.data == "back_to_item")
async def back_to_item_handler(call: CallbackQuery, state: FSMContext):
    """Return to item page, preserving promo state."""
    data = await state.get_data()
    item_name = data.get('csrf_item')
    if not item_name:
        # Fallback
        await call.message.edit_text(
            localize("shop.item.not_found"),
            reply_markup=back("back_to_menu"),
        )
        return
    await _leave_promo_input(state)
    await _render_item_page(call, state, item_name, user_id=call.from_user.id)


# --- Balance Promo Redemption (from profile) ---

@router.callback_query(F.data == "redeem_promo")
async def redeem_promo_handler(call: CallbackQuery, state: FSMContext):
    await call.message.edit_text(localize("promo.enter_redeem_code"), reply_markup=back("profile"))
    await state.set_state(PromoFSM.waiting_redeem_code)


@router.message(PromoFSM.waiting_redeem_code, F.text)
async def redeem_promo_code_handler(message: Message, state: FSMContext):
    code = (message.text or "").strip().upper()
    success, error_key, amount = await redeem_balance_promo(code, message.from_user.id)

    if success:
        await message.answer(
            localize("promo.balance_redeemed", code=code, amount=amount, currency=EnvKeys.PAY_CURRENCY),
            reply_markup=back("profile"),
        )
        log_audit_bg(
            "promo_redeem", user_id=message.from_user.id,
            resource_type="PromoCode", resource_id=code,
        )
    else:
        await message.answer(localize(error_key), reply_markup=back("profile"))

    await state.clear()


# --- Review Handlers ---

@router.callback_query(F.data == "review")
async def start_review_handler(call: CallbackQuery, state: FSMContext):
    if EnvKeys.REVIEWS_ENABLED != "1":
        await call.answer(localize("review.disabled"), show_alert=True)
        return

    item_name = (await state.get_data()).get('csrf_item')
    if not item_name:
        await call.answer(localize("shop.item.not_found"), show_alert=True)
        return

    # Check if user purchased the item
    purchased = await has_purchased_item(call.from_user.id, item_name)
    if not purchased:
        await call.answer(localize("review.not_purchased"), show_alert=True)
        return

    # Check if already reviewed
    existing = await get_user_review(call.from_user.id, item_name)
    if existing:
        await call.answer(localize("review.already_exists"), show_alert=True)
        return

    await state.update_data(review_item_name=item_name)
    await call.message.edit_text(
        localize("review.prompt_rating", name=esc(item_name)),
        reply_markup=rating_keyboard(),
    )
    await state.set_state(ReviewFSM.waiting_rating)


@router.callback_query(F.data.startswith("rating:"), ReviewFSM.waiting_rating)
async def receive_rating_handler(call: CallbackQuery, state: FSMContext):
    try:
        rating = ReviewRequest(rating=int(call.data.split(":")[1])).rating
    except (ValueError, IndexError, ValidationError):
        await call.answer(localize("errors.invalid_data"), show_alert=True)
        return

    await state.update_data(review_rating=rating)

    buttons = [
        (localize("btn.skip_review_text"), "skip_review_text"),
        (localize("btn.back"), "back_to_menu"),
    ]
    await call.message.edit_text(
        localize("review.prompt_text"),
        reply_markup=simple_buttons(buttons),
    )
    await state.set_state(ReviewFSM.waiting_text)


async def _submit_review(user_id: int, state: FSMContext, text: str | None) -> bool:
    """Persist the review accumulated in the FSM. False if it could not be saved.

    The item name and rating come out of state, which an expired session can
    leave empty — create_review also re-validates, so a bad pair is refused
    rather than raised.
    """
    data = await state.get_data()
    item_name = data.get('review_item_name')
    rating = data.get('review_rating')
    if not item_name or rating is None:
        return False

    if await create_review(user_id, item_name, rating, text) is None:
        return False

    await invalidate_rating_cache(item_name)
    return True


@router.callback_query(F.data == "skip_review_text", ReviewFSM.waiting_text)
async def skip_review_text_handler(call: CallbackQuery, state: FSMContext):
    ok = await _submit_review(call.from_user.id, state, None)
    await call.message.edit_text(
        localize("review.created" if ok else "errors.something_wrong"),
        reply_markup=back("back_to_menu"),
    )
    await state.clear()


@router.message(ReviewFSM.waiting_text, F.text)
async def receive_review_text_handler(message: Message, state: FSMContext):
    text = (message.text or "")[:500].strip()

    ok = await _submit_review(message.from_user.id, state, text)
    await message.answer(
        localize("review.created" if ok else "errors.something_wrong"),
        reply_markup=back("back_to_menu"),
    )
    await state.clear()


# --- View Reviews ---

@router.callback_query(F.data.startswith("reviews:"))
async def view_reviews_handler(call: CallbackQuery, state: FSMContext):
    """List an item's reviews. Format: reviews:{page}"""
    if EnvKeys.REVIEWS_ENABLED != "1":
        await call.answer(localize("review.disabled"), show_alert=True)
        return

    try:
        page = int(call.data.split(":")[1])
    except (ValueError, IndexError):
        page = 0

    item_name = (await state.get_data()).get('csrf_item')
    if not item_name:
        await call.answer(localize("shop.item.not_found"), show_alert=True)
        return

    paginator = LazyPaginator(partial(query_item_reviews, item_name), per_page=5)

    reviews = await paginator.get_page(page)
    total_pages = await paginator.get_total_pages()

    if not reviews:
        await call.message.edit_text(
            localize("review.list_empty"),
            reply_markup=back("back_to_item"),
        )
        return

    lines = [localize("review.list_title", name=esc(item_name)), ""]
    for r in reviews:
        if r.get('text'):
            lines.append(localize(
                "review.item", rating=r['rating'],
                text=esc(r['text'][:100]),
            ))
        else:
            lines.append(localize("review.item_no_text", rating=r['rating']))

    # Navigation
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    kb = InlineKeyboardBuilder()
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="◀️", callback_data=f"reviews:{page - 1}"))
    if total_pages > 1:
        nav_buttons.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="dummy_button"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(text="▶️", callback_data=f"reviews:{page + 1}"))
    if nav_buttons:
        kb.row(*nav_buttons)
    kb.row(InlineKeyboardButton(text=localize("btn.back"), callback_data="back_to_item"))

    await call.message.edit_text("\n".join(lines), reply_markup=kb.as_markup())


# --- My orders ---

def _orders_back(page: int) -> str:
    return f"my-orders-page_{page}"


async def _show_orders_page(call: CallbackQuery, user_id: int, page: int):
    """Render one page of the customer's orders, newest first."""
    paginator = LazyPaginator(partial(query_user_orders, user_id), per_page=10)
    if not await paginator.get_total_count():
        await call.message.edit_text(localize("orders.title") + "\n\n" + localize("orders.empty"),
                                     reply_markup=back("profile"))
        return

    markup = await lazy_paginated_keyboard(
        paginator=paginator,
        item_text=lambda o: localize(
            "orders.item", id=o.id, status=localize(f"order.status.{o.status}"),
            total=o.total, currency=EnvKeys.PAY_CURRENCY,
        ),
        item_callback=lambda o: f"my_order:{o.id}:{page}",
        page=page,
        back_cb="profile",
        nav_cb_prefix="my-orders-page_",
    )
    await call.message.edit_text(localize("orders.title"), reply_markup=markup)


@router.callback_query(F.data == "my_orders")
async def my_orders_handler(call: CallbackQuery, state: FSMContext):
    """The customer's order list. First page."""
    await _show_orders_page(call, call.from_user.id, 0)


@router.callback_query(F.data.startswith("my-orders-page_"))
async def navigate_my_orders(call: CallbackQuery, state: FSMContext):
    """Pagination for the order list. Format: my-orders-page_{page}"""
    page = _page_arg(call.data.split("_", 1)[1])
    if page is None:
        await call.answer(localize("errors.pagination_invalid"), show_alert=True)
        return
    await _show_orders_page(call, call.from_user.id, page)


def _order_ref(data: str) -> tuple[int, int] | None:
    """Parse ``prefix:{order_id}[:{page}]`` into (order_id, page)."""
    parts = data.split(":")
    try:
        order_id = int(parts[1])
        page = int(parts[2]) if len(parts) > 2 else 0
    except (ValueError, IndexError):
        return None
    return (order_id, page) if page >= 0 else None


async def _show_order(call: CallbackQuery, order_id: int, page: int):
    """The order card, only ever for the caller's own order."""
    order = await get_order(order_id, user_id=call.from_user.id)
    if not order:
        await call.answer(localize("orders.not_found"), show_alert=True)
        return
    try:
        await call.message.edit_text(
            format_order(order), reply_markup=order_keyboard(order, back_cb=_orders_back(page)),
        )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise


@router.callback_query(F.data.startswith("my_order:"))
async def my_order_handler(call: CallbackQuery, state: FSMContext):
    """Order detail. Format: my_order:{id}[:{page}] (the bare form comes from status notices)."""
    ref = _order_ref(call.data)
    if ref is None:
        await call.answer(localize("errors.invalid_data"), show_alert=True)
        return
    await _show_order(call, *ref)


@router.callback_query(F.data.startswith("my_order_cancel:"))
async def my_order_cancel_ask_handler(call: CallbackQuery, state: FSMContext):
    """Ask before cancelling. Format: my_order_cancel:{id}[:{page}]"""
    ref = _order_ref(call.data)
    if ref is None:
        await call.answer(localize("errors.invalid_data"), show_alert=True)
        return
    order_id, page = ref
    await call.message.edit_text(
        localize("orders.cancel_confirm", id=order_id),
        reply_markup=simple_buttons([
            (localize("btn.yes"), f"my_order_cancel_yes:{order_id}:{page}"),
            (localize("btn.no"), f"my_order:{order_id}:{page}"),
        ]),
    )


@router.callback_query(F.data.startswith("my_order_cancel_yes:"))
async def my_order_cancel_handler(call: CallbackQuery, state: FSMContext):
    """Cancel the caller's own order and put its stock back. Format: my_order_cancel_yes:{id}[:{page}]"""
    ref = _order_ref(call.data)
    if ref is None:
        await call.answer(localize("errors.invalid_data"), show_alert=True)
        return
    order_id, page = ref

    ok, code, order = await cancel_order_transaction(order_id, by_customer_id=call.from_user.id, reason="customer")
    if not ok:
        error_map = {
            "order_not_found": localize("orders.not_found"),
            "not_cancellable": localize("orders.not_cancellable"),
        }
        await call.answer(error_map.get(code, localize("errors.something_wrong")), show_alert=True)
        await _show_order(call, order_id, page)
        return

    await call.answer(localize("orders.cancelled", id=order_id))
    for name in order.get("restocked", []):
        # Waiting customers learn the item is back; don't hold up this reply for the broadcast.
        safe_create_task(notify_restock(call.bot, name))
    await _show_order(call, order_id, page)
