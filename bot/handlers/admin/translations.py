"""Translations editor: the names (and, for products, descriptions) of an existing category/product
in every language. The canonical text is the main language and is edited by the other flows."""
from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.database.methods.audit import log_audit_bg
from bot.database.methods.read import check_category, get_category_by_id, get_item_info, resolve_category_name
from bot.database.methods.translations import set_category_translations, set_item_translations
from bot.database.models import Permission
from bot.filters import HasPermissionFilter
from bot.handlers.admin._common import (
    main_language, other_languages, language_label, check_translation, translation_limit,
    admin_language, wizard_languages,
)
from bot.handlers.admin.categories_management import categories_callback_handler
from bot.handlers.admin.goods_management import _render_card
from bot.handlers.other import caller_name
from bot.i18n import localize, esc
from bot.keyboards.inline import back
from bot.keyboards.translations import editor_keyboard, field_keyboard
from bot.misc.localized import LANGS, pick
from bot.states import TranslationFSM, StockFSM

router = Router()

_PERM = HasPermissionFilter(permission=Permission.CATALOG_MANAGE)
_FIELDS = {'n': 'name', 'd': 'description'}
_PREVIEW = 160          # characters of a description shown on the editor screen
_ERR_CODES = {'category_not_found', 'item_not_found', 'invalid_language', 'invalid_field', 'too_long'}


def _preview(text: str | None, limit: int = _PREVIEW) -> str:
    """HTML-safe, shortened view of a stored text; "not set" when empty."""
    if text is None or not str(text).strip():
        return localize('admin.translations.not_set')
    text = str(text).strip()
    if len(text) > limit:
        text = text[:limit].rstrip() + '…'
    return esc(text)


def _error_text(code: str, field: str) -> str:
    key = f'admin.translations.err.{code}' if code in _ERR_CODES else 'errors.invalid_data'
    return localize(key, max=translation_limit(field))


async def _load(state: FSMContext) -> tuple[str | None, str | None, dict | None]:
    """``(kind, canonical name, fresh row)`` of the edited target; the row is None if it is gone."""
    data = await state.get_data()
    kind, name = data.get('tr_kind'), data.get('tr_name')
    if kind not in ('c', 'i') or not name:
        return None, None, None
    row = await (check_category(name) if kind == 'c' else get_item_info(name))
    return kind, name, row


def _card_text(kind: str, name: str, row: dict, admin_lang: str | None = None,
               parent_name: str | None = None) -> str:
    """The editor text: the three languages, the admin's own first (``admin_lang``), the main one marked."""
    main = main_language()
    lines = [localize('admin.translations.card.title.category' if kind == 'c'
                      else 'admin.translations.card.title.item', name=esc(name)), '']
    if parent_name:
        lines += [localize('admin.translations.card.parent', name=esc(parent_name)), '']
    for lang in wizard_languages(admin_lang):
        is_main = lang == main
        label = language_label(lang)
        if is_main:
            label += f" ({localize('admin.translations.main')})"
        lines.append(f"<b>{label}</b>")
        name_value = row.get('name') if is_main else row.get(f'name_{lang}')
        lines.append(f"{localize('admin.translations.field.name')}: {_preview(name_value)}")
        if kind == 'i':
            desc_value = row.get('description') if is_main else row.get(f'description_{lang}')
            lines.append(f"{localize('admin.translations.field.description')}: {_preview(desc_value)}")
        lines.append('')
    lines.append(localize('admin.translations.card.hint'))
    return "\n".join(lines)


async def _show_card(target: Message, state: FSMContext, *, note: str | None = None, edit: bool = False) -> None:
    """(Re)draw the editor. ``edit`` edits ``target`` in place, otherwise a new message is sent."""
    kind, name, row = await _load(state)
    if not row:
        text = localize('admin.translations.err.category_not_found' if kind == 'c'
                        else 'admin.translations.err.item_not_found')
        await state.clear()
        markup = back('categories_management' if kind == 'c' else 'goods_management')
        await (target.edit_text if edit else target.answer)(text, reply_markup=markup)
        return
    await state.set_state(TranslationFSM.card)
    admin_lang = (await state.get_data()).get('tr_admin_lang')
    parent_name = None
    if kind == 'c' and row.get('parent_id'):
        parent = await get_category_by_id(row['parent_id'])
        parent_name = pick(parent, 'name', admin_lang) if parent else None
    text = _card_text(kind, name, row, admin_lang, parent_name)
    if note:
        text = f"{note}\n\n{text}"
    markup = editor_keyboard([c for c in wizard_languages(admin_lang) if c in other_languages()],
                             with_description=kind == 'i')
    await (target.edit_text if edit else target.answer)(text, parse_mode='HTML', reply_markup=markup)


# --- Entry points

@router.callback_query(F.data == 'tr:cat', _PERM)
async def translations_category_start(call: CallbackQuery, state: FSMContext):
    """Asks for the name of the category to translate."""
    await call.message.edit_text(localize('admin.translations.prompt.category'),
                                 reply_markup=back('categories_management'))
    await state.set_state(TranslationFSM.waiting_category_name)


@router.message(TranslationFSM.waiting_category_name, F.text, _PERM)
async def translations_category_name(message: Message, state: FSMContext):
    """Opens the editor of the category with that name."""
    name = await resolve_category_name(message.text)
    category = await check_category(name) if name else None
    if not category:
        await message.answer(localize('admin.translations.err.category_not_found'),
                             reply_markup=back('categories_management'))
        return
    await state.update_data(tr_kind='c', tr_name=category['name'],
                            tr_admin_lang=await admin_language(message.from_user.id))
    await _show_card(message, state)


@router.callback_query(F.data == 'tr:item', StockFSM.card, _PERM)
async def translations_item_start(call: CallbackQuery, state: FSMContext):
    """Opens the editor of the product whose stock card is shown."""
    data = await state.get_data()
    await state.update_data(tr_kind='i', tr_name=data.get('stock_item_name'),
                            tr_admin_lang=await admin_language(call.from_user.id))
    await call.answer()
    await _show_card(call.message, state, edit=True)


# --- Editor

@router.callback_query(F.data.startswith('tr:e:'), TranslationFSM.card, _PERM)
async def translations_pick_field(call: CallbackQuery, state: FSMContext):
    """A language + field was picked (``tr:e:<lang>:<n|d>``): ask for the text."""
    parts = call.data.split(':')
    lang = parts[2] if len(parts) == 4 else None
    field = _FIELDS.get(parts[3]) if len(parts) == 4 else None
    kind, name, row = await _load(state)
    if lang not in other_languages() or field is None or (field == 'description' and kind != 'i'):
        await call.answer(localize('errors.invalid_data'), show_alert=True)
        return
    if not row:
        await _show_card(call.message, state, edit=True)
        return
    current = row.get(f'{field}_{lang}')
    await call.answer()
    await state.update_data(tr_lang=lang, tr_field=field)
    await state.set_state(TranslationFSM.waiting_text)
    await call.message.edit_text(
        localize(f'admin.translations.prompt.{field}', language=language_label(lang), name=esc(name),
                 current=_preview(current, 300), max=translation_limit(field)),
        parse_mode='HTML', reply_markup=field_keyboard(),
    )


@router.callback_query(F.data == 'tr:card', TranslationFSM.waiting_text, _PERM)
async def translations_back_to_card(call: CallbackQuery, state: FSMContext):
    """Cancels the text prompt and returns to the editor."""
    await call.answer()
    await _show_card(call.message, state, edit=True)


@router.callback_query(F.data == 'tr:back', TranslationFSM.card, _PERM)
async def translations_leave(call: CallbackQuery, state: FSMContext):
    """Leaves the editor: products go back to their stock card, categories to the categories menu."""
    data = await state.get_data()
    await call.answer()
    if data.get('tr_kind') == 'i':
        item = await get_item_info(data.get('tr_name') or '')
        if item:
            await state.set_state(StockFSM.card)
            text, markup = await _render_card(item)
            await call.message.edit_text(text, parse_mode='HTML', reply_markup=markup)
            return
        await state.clear()
        await call.message.edit_text(localize('admin.goods.position.not_found'),
                                     reply_markup=back('goods_management'))
        return
    await state.clear()
    await categories_callback_handler(call)


async def _apply(target: Message, user, state: FSMContext, value: str | None, *, edit: bool) -> None:
    """Save (or clear, ``value`` None) the chosen language/field, audit it and redraw the editor."""
    data = await state.get_data()
    kind, name = data.get('tr_kind'), data.get('tr_name')
    lang, field = data.get('tr_lang'), data.get('tr_field')
    if kind not in ('c', 'i') or not name or lang not in LANGS or field not in _FIELDS.values():
        await state.clear()
        await (target.edit_text if edit else target.answer)(localize('errors.invalid_data'),
                                                            reply_markup=back('goods_management'))
        return
    if kind == 'c':
        ok, code = await set_category_translations(name, {lang: value})
    else:
        ok, code = await set_item_translations(name, {lang: {field: value}})
    if not ok:
        if code in ('category_not_found', 'item_not_found'):
            await state.update_data(tr_lang=None, tr_field=None)
            await _show_card(target, state, edit=edit)       # reports the vanished target
            return
        await (target.edit_text if edit else target.answer)(_error_text(code, field),
                                                            reply_markup=field_keyboard())
        return
    log_audit_bg("update_translation", user_id=user.id, resource_type="Category" if kind == 'c' else "Item",
                 resource_id=name,
                 details=f"admin={user.first_name or user.id}, lang={lang}, field={field}, "
                         f"action={'clear' if value is None else 'set'}")
    await state.update_data(tr_lang=None, tr_field=None)
    note = localize('admin.translations.saved' if value is not None else 'admin.translations.cleared',
                    language=language_label(lang))
    await _show_card(target, state, note=note, edit=edit)


@router.message(TranslationFSM.waiting_text, F.text, _PERM)
async def translations_text(message: Message, state: FSMContext):
    """The typed text for the chosen language and field."""
    data = await state.get_data()
    field = data.get('tr_field')
    if field not in _FIELDS.values():
        await state.clear()
        await message.answer(localize('errors.invalid_data'), reply_markup=back('goods_management'))
        return
    value, error = check_translation(field, message.text)
    if error:
        await message.answer(localize(error, max=translation_limit(field)), reply_markup=field_keyboard())
        return
    await _apply(message, message.from_user, state, value, edit=False)


@router.callback_query(F.data == 'tr:clear', TranslationFSM.waiting_text, _PERM)
async def translations_clear(call: CallbackQuery, state: FSMContext):
    """Removes the translation: the main-language text is shown instead."""
    await call.answer()
    await _apply(call.message, call.from_user, state, None, edit=True)
