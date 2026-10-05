from aiogram import Router, F
from aiogram.types import CallbackQuery, Message

from bot.i18n import localize, esc
from bot.handlers.other import caller_name
from bot.database.models import Permission
from bot.database.methods import create_category, delete_category, update_category
from bot.database.methods.read import resolve_category_name
from bot.handlers.admin._common import (
    admin_language, main_language, wizard_languages, language_label, check_translation, translation_limit,
)
from bot.misc.localized import derive_canonical
from bot.keyboards.inline import back, simple_buttons
from bot.keyboards.translations import skip_keyboard
from bot.filters import HasPermissionFilter
from bot.database.methods.audit import log_audit
from bot.misc import CategoryRequest
from bot.states import CategoryFSM

router = Router()


async def wizard_languages_for(user_id) -> list[str]:
    """Language steps of the add wizard for this admin: their own language first, then the others."""
    return wizard_languages(await admin_language(user_id))


@router.callback_query(F.data == 'categories_management', HasPermissionFilter(permission=Permission.CATALOG_MANAGE))
async def categories_callback_handler(call: CallbackQuery):
    """
    Opens the categories management submenu.
    """
    actions = [
        (localize("admin.categories.add"), "add_category"),
        (localize("admin.categories.rename"), "update_category"),
        (localize("admin.translations.btn.open"), "tr:cat"),
        (localize("admin.categories.delete"), "delete_category"),
        (localize("btn.back"), "console"),
    ]
    await call.message.edit_text(
        localize("admin.categories.menu.title"),
        reply_markup=simple_buttons(actions, per_row=1),
    )


@router.callback_query(F.data == 'add_category', HasPermissionFilter(permission=Permission.CATALOG_MANAGE))
async def add_category_callback_handler(call: CallbackQuery, state):
    """
    Asks admin for a new category name, first in the admin's own language.
    """
    admin_lang = (await wizard_languages_for(call.from_user.id))[0]
    await call.message.edit_text(
        localize("admin.categories.prompt.add", language=language_label(admin_lang)),
        reply_markup=back("categories_management"),
    )
    await state.set_state(CategoryFSM.waiting_add_category)


@router.message(CategoryFSM.waiting_add_category, F.text)
async def process_category_for_add(message: Message, state):
    """Checks the name in the admin's own language (required), then asks for the other languages (each
    skippable). The canonical name is derived when the wizard ends (see ``_create_category_with_names``)."""
    try:
        # Validate category name
        category_request = CategoryRequest(name=message.text.strip())
        category_name = category_request.sanitize_name()
        if not category_name:
            raise ValueError("empty category name")

        if await resolve_category_name(category_name):
            await message.answer(
                localize("admin.categories.add.exist"),
                reply_markup=back("categories_management"),
            )
            await state.clear()
            return
    except Exception as e:
        await message.answer(
            localize("errors.invalid_data"),
            reply_markup=back("categories_management"),
        )
        await log_audit("create_category_error", level="ERROR", user_id=message.from_user.id, resource_type="Category",
                        details=str(e))
        await state.clear()
        return

    languages = await wizard_languages_for(message.from_user.id)
    await state.update_data(cat_lang=languages[0], cat_names={languages[0]: category_name},
                            cat_queue=languages[1:])
    await _next_category_translation(message, message.from_user, state)


async def _next_category_translation(target: Message, user, state):
    """Asks for the next language's name, or creates the category when none are left."""
    data = await state.get_data()
    queue = list(data.get("cat_queue") or [])
    if not queue:
        await _create_category_with_names(target, user, state)
        return
    await target.answer(
        localize("admin.categories.add.prompt.translation", language=language_label(queue[0])),
        reply_markup=skip_keyboard("cat_tr_skip", "categories_management"),
    )
    await state.set_state(CategoryFSM.waiting_add_category_translation)


@router.message(CategoryFSM.waiting_add_category_translation, F.text,
                HasPermissionFilter(permission=Permission.CATALOG_MANAGE))
async def process_category_translation(message: Message, state):
    """Takes the name in the current language (validated) and moves on."""
    data = await state.get_data()
    queue = list(data.get("cat_queue") or [])
    if not queue:
        await _create_category_with_names(message, message.from_user, state)
        return
    value, error = check_translation("name", message.text)
    if error:
        await message.answer(
            localize(error, max=translation_limit("name")),
            reply_markup=skip_keyboard("cat_tr_skip", "categories_management"),
        )
        return
    if await resolve_category_name(value):
        await message.answer(
            localize("admin.categories.add.exist"),
            reply_markup=skip_keyboard("cat_tr_skip", "categories_management"),
        )
        return
    names = dict(data.get("cat_names") or {})
    names[queue[0]] = value
    await state.update_data(cat_names=names, cat_queue=queue[1:])
    await _next_category_translation(message, message.from_user, state)


@router.callback_query(F.data == 'cat_tr_skip', CategoryFSM.waiting_add_category_translation,
                       HasPermissionFilter(permission=Permission.CATALOG_MANAGE))
async def skip_category_translation(call: CallbackQuery, state):
    """Leaves the current language empty (it falls back to the main-language name)."""
    await call.answer()
    data = await state.get_data()
    await state.update_data(cat_queue=list(data.get("cat_queue") or [])[1:])
    await _next_category_translation(call.message, call.from_user, state)


async def _create_category_with_names(target: Message, user, state):
    """Creates the category with the collected names; ``target`` is where replies go, ``user`` is the
    admin who acted.

    The canonical name is the main-language (BOT_LOCALE) text if it was entered, else the admin's own
    language text, else the first filled one. Every entered language is stored as its ``name_<lang>``;
    ``name_<main>`` is therefore set only when the canonical IS the main-language text, otherwise it
    stays NULL (the canonical shows instead)."""
    data = await state.get_data()
    names = dict(data.get("cat_names") or {})
    category_name = derive_canonical(names, main_language(), data.get("cat_lang"))
    await state.clear()
    if not category_name:
        await target.answer(localize("errors.invalid_data"), reply_markup=back("categories_management"))
        return
    await create_category(category_name, names=names)
    await target.answer(
        localize("admin.categories.add.success"),
        reply_markup=back("categories_management"),
    )
    await log_audit("create_category", user_id=user.id, resource_type="Category", resource_id=category_name,
                    details=f"admin={user.first_name or user.id}, translations={','.join(sorted(names)) or '-'}")


@router.callback_query(F.data == 'delete_category', HasPermissionFilter(permission=Permission.CATALOG_MANAGE))
async def delete_category_callback_handler(call: CallbackQuery, state):
    """
    Asks admin for a category name to delete.
    """
    await call.message.edit_text(
        localize("admin.categories.prompt.delete"),
        reply_markup=back("categories_management"),
    )
    await state.set_state(CategoryFSM.waiting_delete_category)


# --- Handle category deletion
@router.message(CategoryFSM.waiting_delete_category, F.text)
async def process_category_for_delete(message: Message, state):
    """
    Deletes a category by name if it exists.
    """
    category_name = await resolve_category_name(message.text)

    if not category_name:
        await message.answer(
            localize("admin.categories.delete.not_found"),
            reply_markup=back("categories_management"),
        )
    else:
        await delete_category(category_name)
        await message.answer(
            localize("admin.categories.delete.success"),
            reply_markup=back("categories_management"),
        )
        admin_name = caller_name(message)
        await log_audit("delete_category", user_id=message.from_user.id, resource_type="Category",
                        resource_id=category_name, details=f"admin={admin_name}")

    await state.clear()


@router.callback_query(F.data == 'update_category', HasPermissionFilter(permission=Permission.CATALOG_MANAGE))
async def update_category_callback_handler(call: CallbackQuery, state):
    """
    Asks admin for current category name before renaming.
    """
    await call.message.edit_text(
        localize("admin.categories.prompt.rename.old"),
        reply_markup=back("categories_management"),
    )
    await state.set_state(CategoryFSM.waiting_update_category)


@router.message(CategoryFSM.waiting_update_category, F.text)
async def check_category_for_update(message: Message, state):
    """
    Verifies the category exists, then prompts for a new name.
    """
    old_name = await resolve_category_name(message.text)

    if not old_name:
        await message.answer(
            localize("admin.categories.rename.not_found"),
            reply_markup=back("categories_management"),
        )
        await state.clear()
        return

    await state.update_data(old_category=old_name)
    await message.answer(
        localize("admin.categories.prompt.rename.new"),
        reply_markup=back("categories_management"),
    )
    await state.set_state(CategoryFSM.waiting_update_category_name)


@router.message(CategoryFSM.waiting_update_category_name, F.text)
async def check_category_name_for_update(message: Message, state):
    """
    Renames a category to the new name.
    """
    try:
        new_name = CategoryRequest(name=message.text.strip()).sanitize_name()
        if not new_name:
            raise ValueError("empty category name")
    except Exception as e:
        await message.answer(localize("errors.invalid_data"), reply_markup=back("categories_management"))
        await log_audit("rename_category_error", level="ERROR", user_id=message.from_user.id,
                        resource_type="Category", details=str(e))
        await state.clear()
        return
    data = await state.get_data()
    old_name = data.get("old_category")

    existing = await resolve_category_name(new_name)
    # Taken by another category, or unchanged; a translation of the category itself may become its canonical name.
    if existing and (existing != old_name or new_name == old_name):
        await message.answer(
            localize("admin.categories.rename.exist"),
            reply_markup=back("categories_management"),
        )
        await state.clear()
        return

    await update_category(old_name, new_name)
    await message.answer(
        localize("admin.categories.rename.success", old=esc(old_name), new=esc(new_name)),
        reply_markup=back("categories_management"),
    )

    admin_name = caller_name(message)
    await log_audit("rename_category", user_id=message.from_user.id, resource_type="Category", resource_id=new_name,
                    details=f"admin={admin_name}, old_name={old_name}")

    await state.clear()
