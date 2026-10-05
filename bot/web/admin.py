import asyncio
import json
import logging
import os
import re
import time
from decimal import Decimal, InvalidOperation
from typing import Any

from sqladmin import Admin, ModelView, action
from sqladmin.authentication import AuthenticationBackend
from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware
from starlette.routing import Route
from sqlalchemy import text

from markupsafe import Markup, escape
from wtforms import BooleanField, Field, FileField, Form, SelectField, StringField, TextAreaField
from wtforms.validators import Optional as WtfOptional, StopValidation
from sqlalchemy import select as sa_select, update as sa_update, func as sa_func

from bot.misc import EnvKeys
from bot.database.methods.audit import log_audit
from bot.database.methods.web_users import get_web_user_auth, record_web_login
from bot.i18n import main as i18n_main
from bot.i18n.main import LANGUAGES, current_language, localize, set_language
from bot.web.language import LanguageMiddleware, LazyText, Localized, cookie_language, error_text
from bot.web.passwords import DUMMY_HASH, verify_password
from bot.web.session import current_web_user

logger = logging.getLogger(__name__)


def _client_ip(request: Request) -> str:
    """Resolve the real client IP, trusting X-Forwarded-For only from loopback.

    When a reverse proxy on the same host fronts the panel, request.client.host
    is 127.0.0.1; the original client is then the first hop of X-Forwarded-For.
    That header ONLY when the socket peer is loopback, so an external
    client cannot spoof its IP (which would otherwise defeat the default-cred
    guard and the login rate limiter).
    """
    peer = request.client.host if request.client else ""
    if peer in ("127.0.0.1", "::1"):
        fwd = request.headers.get("x-forwarded-for", "")
        if fwd:
            return fwd.split(",")[0].strip()
    return peer


class LoginRateLimiter:
    """In-memory rate limiter for login attempts by IP."""

    def __init__(self, max_attempts: int = 5, lockout_seconds: int = 900):
        self.max_attempts = max_attempts
        self.lockout_seconds = lockout_seconds
        self._attempts: dict[str, list[float]] = {}
        self._last_cleanup: float = time.time()

    def is_blocked(self, ip: str) -> bool:
        if ip not in self._attempts:
            return False
        now = time.time()
        self._attempts[ip] = [t for t in self._attempts[ip] if now - t < self.lockout_seconds]
        return len(self._attempts[ip]) >= self.max_attempts

    def record_failure(self, ip: str) -> None:
        now = time.time()
        if now - self._last_cleanup > 600:
            self._attempts = {
                k: [t for t in v if now - t < self.lockout_seconds]
                for k, v in self._attempts.items()
                if any(now - t < self.lockout_seconds for t in v)
            }
            self._last_cleanup = now
        if ip not in self._attempts:
            self._attempts[ip] = []
        self._attempts[ip].append(now)

    def reset(self, ip: str) -> None:
        self._attempts.pop(ip, None)


_login_limiter = LoginRateLimiter()
from bot.database.main import Database
from bot.database.models.main import (
    User, Role, Categories, Goods, Orders, OrderItems, Operations, ReferralEarnings,
    AuditLog, PromoCodes, CartItems, Reviews, promo_scope_for,
    OrderStatus, PaymentMethod, PaymentStatus, WebRole,
)
from bot.misc.images import ImageError, validate_image
from bot.misc.localized import (
    LANGS, MAX_DESCRIPTION_LEN, MAX_NAME_LEN, clean_description, clean_name, derive_canonical, pick,
)
from bot.misc.metrics import get_metrics
from bot.misc.caching import get_cache_manager
from bot.database.methods.read import (
    invalidate_user_cache, invalidate_item_cache, invalidate_rating_cache, get_item_name_by_id,
    invalidate_category_cache, parent_assignment_error,
)
from bot.database.methods.cache_utils import safe_create_task
from bot.database.methods.delete import delete_item
from bot.database.methods.item_options import (
    OptionsError, check_option_names_free, format_options_text, parse_options_text, plain_price,
    sync_item_options,
)
from bot.database.methods.product_images import items_with_images, remove_item_image, set_item_image
from bot.database.methods.orders import set_order_status, confirm_mia_payment
from bot.misc.services.restock_notifier import notify_restock
from bot.misc.services.order_view import notify_customer
from bot.middleware.security import invalidate_auth_caches, flush_all_role_caches


# Authentication
class AdminAuth(AuthenticationBackend):
    def __init__(self, secret_key: str) -> None:
        super().__init__(secret_key)
        # The panel app already carries the one SessionMiddleware (with the cookie flags); a second one
        # inside SQLAdmin would write its own copy of the session over it.
        self.middlewares = []

    async def login(self, request: Request) -> bool:
        ip = _client_ip(request)

        if _login_limiter.is_blocked(ip):
            await log_audit("web_login_blocked", level="WARNING", details=f"ip={ip}", ip_address=ip)
            return False

        form = await request.form()
        username = str(form.get("username") or "").strip()
        password = str(form.get("password") or "")

        user = await get_web_user_auth(username) if username else None
        # An unknown username costs the same hash as a wrong password, so timing doesn't reveal which exist.
        verified = await asyncio.to_thread(
            verify_password, password, user["password_hash"] if user else DUMMY_HASH
        )
        if user is not None and verified:
            if not user["is_active"]:
                _login_limiter.record_failure(ip)
                await log_audit("web_login_failed", level="WARNING", details=f"user={username}, reason=inactive",
                                ip_address=ip)
                return False
            if password == "admin" and ip not in ("127.0.0.1", "::1", "localhost"):
                await log_audit("web_login_blocked_default_creds", level="WARNING",
                                details=f"user={username}, ip={ip}", ip_address=ip)
                return False
            chosen = cookie_language(request)
            await record_web_login(user["id"], chosen)
            session = {"uid": user["id"], "role": user["role"]}
            lang = user["language"] or chosen
            if lang:
                session["lang"] = lang
            request.session.clear()
            request.session.update(session)
            _login_limiter.reset(ip)
            await log_audit("web_login", user_id=None, details=f"user={username}, role={user['role']}", ip_address=ip)
            return True

        _login_limiter.record_failure(ip)
        await log_audit("web_login_failed", level="WARNING", details=f"user={username}", ip_address=ip)
        return False

    async def logout(self, request: Request) -> bool:
        await log_audit("web_logout", details=f"uid={request.session.get('uid')}", ip_address=_client_ip(request))
        request.session.clear()
        return True

    async def authenticate(self, request: Request) -> bool:
        user = await current_web_user(request)
        if user is None:
            request.session.clear()
            return False
        # The account's own language wins; keep the session in step when it was changed elsewhere.
        if user["language"] and request.session.get("lang") != user["language"]:
            request.session["lang"] = user["language"]
        if user["language"]:
            set_language(user["language"])   # this very request already renders in it
        return True


def _safe_model_repr(model: Any, max_len: int = 500) -> str:
    """Return a truncated repr that excludes sensitive fields."""
    _sensitive = {"balance", "password", "password_hash", "secret", "token", "value"}
    parts = []
    for col in getattr(model, "__table__", None).columns if hasattr(model, "__table__") else ():
        if col.name in _sensitive or "password" in col.name:
            continue
        val = getattr(model, col.name, None)
        parts.append(f"{col.name}={val!r}")
    result = f"{type(model).__name__}({', '.join(parts)})"
    return result[:max_len]


_notifier_bot: Any = None


def set_notifier_bot(bot: Any) -> None:
    global _notifier_bot
    _notifier_bot = bot


class LocalizedModelView(ModelView):
    """ModelView whose column labels follow the request language.

    SQLAdmin builds ``_column_labels`` once; here it is computed per access: the ``web.col.<column>``
    translation, else a label given in ``column_labels``, else the column name.
    """

    @property
    def _column_labels(self) -> dict:
        given = self.__dict__.get("_given_labels", {})
        names = list(self._prop_names) + [n for n in getattr(self, "_list_prop_names", []) if n not in self._prop_names]
        labels = {}
        for prop in names:
            key = f"web.col.{prop}"
            text = localize(key)
            # The language field of the signed-in admin's own language is simply "Name" / "Description".
            own = re.fullmatch(r"(name|description)_(en|ru|ro)", prop)
            if own and own.group(2) == current_language():
                text = localize(f"web.col.{own.group(1)}")
            labels[prop] = given.get(prop, prop) if text == key else text
        return labels

    @_column_labels.setter
    def _column_labels(self, value: dict) -> None:
        self.__dict__["_given_labels"] = value


# Audited base view for mutable models
class AuditModelView(LocalizedModelView):
    async def after_model_change(self, data: dict, model: Any, is_created: bool, request: Request) -> None:
        action = f"sqladmin_{'create' if is_created else 'update'}"
        await log_audit(
            action,
            resource_type=type(self).name,
            resource_id=str(getattr(model, 'id', getattr(model, 'name', None))),
            details=_safe_model_repr(model),
            ip_address=_client_ip(request),
        )

    async def after_model_delete(self, model: Any, request: Request) -> None:
        await log_audit(
            "sqladmin_delete",
            resource_type=type(self).name,
            resource_id=str(getattr(model, 'id', getattr(model, 'name', None))),
            details=_safe_model_repr(model),
            ip_address=_client_ip(request),
        )


# Model Views
class UserAdmin(AuditModelView, model=User):
    column_list = [User.telegram_id, User.balance, User.role_id, User.referral_id,
                   User.registration_date, User.is_blocked]
    column_searchable_list = [User.telegram_id]
    column_sortable_list = [User.telegram_id, User.balance, User.registration_date]
    column_default_sort = (User.registration_date, True)
    form_excluded_columns = [
        User.user_operations, User.user_orders,
        User.referral_earnings_received, User.referral_earnings_generated,
    ]
    name = Localized("web.model.user.one")
    name_plural = Localized("web.model.user.many")
    icon = "fa-solid fa-users"

    async def _invalidate(self, model: Any, *, blocked: bool | None = None) -> None:
        # A web edit of balance/role_id/is_blocked would otherwise be served stale
        # from Redis (user/role, up to 600s) and from the middleware's in-memory
        # role cache + blocked set (until restart). Clear both; the blocked set
        # is authoritative per-update, so pass the new block state explicitly.
        tid = getattr(model, "telegram_id", None)
        if tid is not None:
            safe_create_task(invalidate_user_cache(int(tid)))
            invalidate_auth_caches(int(tid), blocked=blocked)

    async def after_model_change(self, data: dict, model: Any, is_created: bool, request: Request) -> None:
        await super().after_model_change(data, model, is_created, request)
        await self._invalidate(model, blocked=bool(getattr(model, "is_blocked", False)))

    async def after_model_delete(self, model: Any, request: Request) -> None:
        await super().after_model_delete(model, request)
        await self._invalidate(model, blocked=False)


_PERM_FLAGS = [
    (1,   "USE"),
    (2,   "BROADCAST"),
    (4,   "SETTINGS"),
    (8,   "USERS"),
    (16,  "CATALOG"),
    (32,  "ADMINS"),
    (64,  "OWNER"),
    (128, "STATS"),
    (256, "BALANCE"),
    (512, "PROMOS"),
    (1024, "ORDERS"),
]


def _perm_label(flag: str) -> str:
    return localize(f"web.perm.{flag}")


class PermissionsWidget:
    """One toggle tag per permission; the saved number is just the sum of the ticked tags."""

    def __call__(self, field, **kwargs):
        current = int(field.data or 0)
        tags = []
        for bit, flag in _PERM_FLAGS:
            checked = " checked" if current & bit else ""
            tags.append(
                f'<label class="form-selectgroup-item"><input type="checkbox" name="{escape(field.name)}" '
                f'value="{bit}" class="form-selectgroup-input"{checked}>'
                f'<span class="form-selectgroup-label">{escape(_perm_label(flag))}</span></label>')
        # A hidden 0 keeps the field present in the post when no tag is ticked.
        return Markup(f'<input type="hidden" name="{escape(field.name)}" value="0">'
                      f'<div class="form-selectgroup">{"".join(tags)}</div>')


class PermissionsField(Field):
    widget = PermissionsWidget()

    def process_formdata(self, valuelist):
        total = 0
        for value in valuelist:
            if str(value).isdigit():
                total |= int(value)
        self.data = total

    def _value(self):
        return str(self.data or 0)


def _format_perms_html(model, name):
    perms = getattr(model, name, 0) or 0
    if not perms:
        return Markup('<span style="color:#999">\u2014</span>')
    badges = []
    for bit, flag in _PERM_FLAGS:
        if perms & bit:
            badges.append(
                f'<span style="display:inline-block;background:#e2e8f0;padding:1px 6px;'
                f'border-radius:4px;margin:1px;font-size:12px">{escape(_perm_label(flag))}</span>'
            )
    return Markup(" ".join(badges))


class RoleAdmin(AuditModelView, model=Role):
    column_list = [Role.id, Role.name, Role.default, Role.permissions]
    column_details_exclude_list = ["users"]
    form_excluded_columns = [Role.users]
    column_sortable_list = [Role.id, Role.name]
    name = Localized("web.model.role.one")
    name_plural = Localized("web.model.role.many")
    icon = "fa-solid fa-shield-halved"
    column_formatters = {"permissions": _format_perms_html}
    column_formatters_detail = {"permissions": _format_perms_html}
    async def scaffold_form(self, *args, **kwargs):
        """Permissions as toggle tags instead of a bitmask number."""
        Base = await super().scaffold_form(*args, **kwargs)
        field = PermissionsField(localize("web.col.permissions"), description=localize("web.form.permissions_hint"))
        if hasattr(Base, "permissions"):
            field.creation_counter = Base.permissions.creation_counter

        class RoleForm(Base):
            permissions = field

        return RoleForm

    @staticmethod
    async def _flush_role_caches() -> None:
        # A Role's permission bitmask affects every user holding that role, so
        # invalidation cannot be scoped to one id: flush all role caches.
        await flush_all_role_caches()

    async def after_model_change(self, data: dict, model: Any, is_created: bool, request: Request) -> None:
        await super().after_model_change(data, model, is_created, request)
        await self._flush_role_caches()

    async def after_model_delete(self, model: Any, request: Request) -> None:
        await super().after_model_delete(model, request)
        await self._flush_role_caches()


def _viewer_language() -> str:
    """The admin's interface language when it is one of the catalog languages, else the shop's main one."""
    lang = current_language()
    return lang if lang in LANGS else i18n_main.get_locale()


def _translation_fields(descriptions: bool) -> list[str]:
    fields = [f"name_{lang}" for lang in LANGS]
    return fields + ([f"description_{lang}" for lang in LANGS] if descriptions else [])


def _name_length_validator(lang: str):
    """Translated replacement for the generic max-length message SQLAdmin adds to String columns.

    Raising StopValidation keeps that English-only validator from also running.
    """
    def check(form, field):
        value = clean_name(field.data)
        if value is not None and len(value) > MAX_NAME_LEN:
            raise StopValidation(localize("web.form.tr_too_long_name",
                                          language=localize(f"web.form.lang.{lang}"), limit=MAX_NAME_LEN))
    return check


def _field_hint(base: str, lang: str) -> str:
    """The hint under a language field: required for the admin's own language, else what empty means."""
    language = localize(f"web.form.lang.{lang}")
    main = i18n_main.get_locale()
    if lang == _viewer_language():
        key = f"web.form.{base}_own_main_hint" if lang == main else f"web.form.{base}_own_hint"
        return localize(key, language=language)
    if lang == main:
        return localize(f"web.form.{base}_main_hint", language=language)
    return localize(f"web.form.{base}_tr_hint", language=language)


def _translation_form_args(descriptions: bool) -> dict:
    """Per-language field hints, in the request language."""
    args = {}
    for lang in LANGS:
        args[f"name_{lang}"] = {"description": _field_hint("name", lang),
                                "validators": [_name_length_validator(lang)]}
        if descriptions:
            args[f"description_{lang}"] = {"description": _field_hint("description", lang)}
    return args


def _translation_widget_args(descriptions: bool) -> dict:
    """SQLAdmin's stock templates do not print a field's ``description``, so the same hint is also the
    placeholder: it shows in the empty field, which is exactly when the fallback matters."""
    args = {k: {"placeholder": v["description"]} for k, v in _translation_form_args(descriptions).items()}
    for lang in LANGS:
        if descriptions:
            args[f"description_{lang}"]["rows"] = 5
    return args


def _own_language_first(form_class, bases: tuple[str, ...], viewer: str) -> None:
    """Put the field of the admin's own language right after the previous field, then the other languages.

    WTForms orders fields by creation counter; the three language fields of one base keep the same set of
    counters, just handed out starting with the viewer's language."""
    for base in bases:
        fields = {lang: getattr(form_class, f"{base}_{lang}") for lang in LANGS if hasattr(form_class, f"{base}_{lang}")}
        order = [lang for lang in [viewer] + [l for l in LANGS if l != viewer] if lang in fields]
        for lang, counter in zip(order, sorted(f.creation_counter for f in fields.values())):
            fields[lang].creation_counter = counter


class TranslatedModelView(AuditModelView):
    """Categories and products: three language fields instead of the canonical ``name`` / ``description``.

    The field of the admin's interface language is labelled plain "Name" / "Description". The canonical
    columns (the unique lookup keys, in the shop's main language) are derived on save with
    ``derive_canonical`` and are not in the form.
    """
    translates_description = False

    def _bases(self) -> tuple[str, ...]:
        return ("name", "description") if self.translates_description else ("name",)

    async def get_object_for_edit(self, value: Any) -> Any:
        """Legacy rows have no main-language translation: show the canonical text in that field."""
        obj = await super().get_object_for_edit(value)
        if obj is not None:
            main = i18n_main.get_locale()
            for base in self._bases():
                if not (getattr(obj, f"{base}_{main}", None) or "").strip():
                    setattr(obj, f"{base}_{main}", getattr(obj, base, None))
        return obj

    async def get_list_value(self, obj: Any, prop: str):
        if prop in self._bases():
            return getattr(obj, prop, None), pick(obj, prop, _viewer_language())
        return await super().get_list_value(obj, prop)

    async def _apply_translations(self, data: dict, model: Any, is_created: bool) -> None:
        """Clean and check the submitted language fields, then derive the canonical text into ``data``."""
        main = i18n_main.get_locale()
        viewer = _viewer_language()
        for base, cleaner, limit, too_long in (
            ("name", clean_name, MAX_NAME_LEN, "web.form.tr_too_long_name"),
            ("description", clean_description, MAX_DESCRIPTION_LEN, "web.form.tr_too_long_description"),
        ):
            if base not in self._bases():
                continue
            texts: dict[str, str | None] = {}
            for lang in LANGS:
                key = f"{base}_{lang}"
                value = cleaner(data[key]) if key in data else None
                if value is not None and len(value) > limit:
                    raise ValueError(localize(too_long, language=localize(f"web.form.lang.{lang}"), limit=limit))
                if key in data:
                    data[key] = value
                texts[lang] = value
            required = ValueError(localize(f"web.form.{base}_required", language=localize(f"web.form.lang.{viewer}")))
            if is_created and not texts.get(viewer):
                raise required
            old = None if is_created else getattr(model, base, None)
            # An edit with the main-language field blank must not rename the item.
            canonical = old if old and not texts.get(main) else derive_canonical(texts, main, viewer)
            if not canonical:
                raise required
            data[base] = canonical
            data[f"{base}_{main}"] = canonical
            if base == "name":
                await self._check_name_free(canonical, model)

    async def _check_name_free(self, name: str, model: Any) -> None:
        stmt = sa_select(self.model.id).where(self.model.name == name)
        own_id = getattr(model, "id", None)
        if own_id is not None:
            stmt = stmt.where(self.model.id != own_id)
        async with Database().session() as session:
            taken = (await session.execute(stmt.limit(1))).first() is not None
        if taken:
            raise ValueError(localize("web.form.name_taken", name=name))


_PARENT_ERRORS = {
    "self_parent": "web.form.parent_self",
    "parent_not_top_level": "web.form.parent_not_top_level",
    "has_children": "web.form.parent_has_children",
    "parent_has_items": "web.form.parent_has_items",
}


class CategoryAdmin(TranslatedModelView, model=Categories):
    column_list = [Categories.name, "parent"]
    column_searchable_list = [Categories.name, Categories.name_en, Categories.name_ru, Categories.name_ro]
    form_columns = _translation_fields(False)
    name = Localized("web.model.category.one")
    name_plural = Localized("web.model.category.many")
    icon = "fa-solid fa-folder"

    @property
    def form_args(self) -> dict:
        return _translation_form_args(False)

    @property
    def form_widget_args(self) -> dict:
        return _translation_widget_args(False)

    async def scaffold_form(self, *args, **kwargs):
        """The parent select (top-level categories only; empty = top-level), in the request language."""
        Base = await super().scaffold_form(*args, **kwargs)
        async with Database().session() as session:
            tops = (await session.execute(
                sa_select(Categories).where(Categories.parent_id.is_(None)).order_by(Categories.name)
            )).scalars().all()
        viewer = _viewer_language()
        _own_language_first(Base, ("name",), viewer)      # the name in the admin's language comes first
        choices = [("", localize("web.form.parent_none"))] + [(str(c.id), pick(c, "name", viewer)) for c in tops]

        def coerce(value):
            return None if value in (None, "", "None") else int(value)

        class CategoryForm(Base):
            parent_id = SelectField(localize("web.col.parent"), choices=choices, coerce=coerce,
                                    validate_choice=False, validators=[WtfOptional()],
                                    description=localize("web.form.parent_hint"),
                                    render_kw={"class": "form-select"})

        return CategoryForm

    async def list(self, request: Request):
        pagination = await super().list(request)
        ids = {r.parent_id for r in pagination.rows if r.parent_id}
        parents = {}
        if ids:
            async with Database().session() as session:
                parents = {c.id: c for c in (await session.execute(
                    sa_select(Categories).where(Categories.id.in_(ids)))).scalars().all()}
        for row in pagination.rows:
            row.parent_row = parents.get(row.parent_id)
        return pagination

    async def get_list_value(self, obj: Any, prop: str):
        if prop == "parent":
            parent = getattr(obj, "parent_row", None)
            if parent is None:
                return None, ""
            return parent.name, pick(parent, "name", _viewer_language())
        return await super().get_list_value(obj, prop)

    async def _validate_parent(self, data: dict, model: Any, is_created: bool) -> None:
        """Refuse a parent that would break the two-level rule; the checks are shared with the bot."""
        if "parent_id" not in data:
            return
        parent_id = data["parent_id"] or None
        data["parent_id"] = parent_id
        if parent_id is None or (not is_created and parent_id == getattr(model, "parent_id", None)):
            return                                    # top-level, or the parent is not being changed
        async with Database().session() as session:
            parent = await session.get(Categories, parent_id)
            if parent is None:
                raise ValueError(localize("web.form.parent_unknown"))
            error = await parent_assignment_error(session, parent, None if is_created else model.id)
        if error:
            raise ValueError(localize(_PARENT_ERRORS[error]))

    async def on_model_change(self, data: dict, model: Any, is_created: bool, request: Request) -> None:
        # On an edit `model` still holds the pre-edit name here; remember it for the cache invalidation.
        request.state.category_old_name = None if is_created else getattr(model, "name", None)
        request.state.category_old_parent_id = None if is_created else getattr(model, "parent_id", None)
        await self._apply_translations(data, model, is_created)
        await self._validate_parent(data, model, is_created)

    async def on_model_delete(self, model: Any, request: Request) -> None:
        async with Database().session() as session:
            has_children = (await session.execute(
                sa_select(Categories.id).where(Categories.parent_id == model.id).limit(1))).first() is not None
        if has_children:
            raise HTTPException(status_code=409, detail=localize("web.category.delete_has_children"))

    async def _invalidate(self, model: Any, old_name: str | None = None, parent_ids=()) -> None:
        # Every translation rides in the cached `category:<name>` row, so any edit drops it (and the old
        # key on a rename). The old and the new parent's entries go too: their subcategories changed.
        names = {n for n in (getattr(model, "name", None), old_name) if n}
        for parent_id in {p for p in parent_ids if p}:
            async with Database().session() as session:
                parent_name = (await session.execute(
                    sa_select(Categories.name).where(Categories.id == parent_id))).scalar()
            if parent_name:
                names.add(parent_name)
        for name in names:
            safe_create_task(invalidate_category_cache(name))

    async def after_model_change(self, data: dict, model: Any, is_created: bool, request: Request) -> None:
        await super().after_model_change(data, model, is_created, request)
        await self._invalidate(model, getattr(request.state, "category_old_name", None),
                               (getattr(request.state, "category_old_parent_id", None),
                                getattr(model, "parent_id", None)))

    async def after_model_delete(self, model: Any, request: Request) -> None:
        await super().after_model_delete(model, request)
        await self._invalidate(model, parent_ids=(getattr(model, "parent_id", None),))


_PICTURE_ERRORS = ("too_large", "invalid_image", "unsupported_format", "item_not_found")


def _picture_error(code: str) -> str:
    return localize(f"web.picture.err.{code if code in _PICTURE_ERRORS else 'invalid_image'}")


# SQLAdmin looks the upload field up on the edited object when the file input is left empty; the picture
# lives in its own table, so the product only needs a harmless placeholder for that lookup.
Goods.picture = None


class OptionsWidget:
    """The weight options as add/remove rows (option, price, quantity) with a "+" button.

    The posted value is still the plain ``label | price | stock`` text of a (hidden) textarea, which a small
    script keeps in sync with the rows; without JavaScript the textarea itself stays editable."""

    def __call__(self, field, **kwargs):
        element_id = kwargs.get("id") or field.id
        labels = {"option": localize("web.form.options_option"), "price": localize("web.col.price"),
                  "stock": localize("web.col.stock"), "add": localize("web.form.options_add"),
                  "remove": localize("web.form.options_remove"), "placeholder": localize("web.form.options_label_placeholder")}
        script = _OPTIONS_SCRIPT.replace("__ID__", json.dumps(element_id)).replace(
            "__LABELS__", json.dumps(labels, ensure_ascii=False).replace("</", "<\\/"))
        textarea = (f'<textarea id="{escape(element_id)}" name="{escape(field.name)}" class="form-control" rows="4" '
                    f'placeholder="{escape(localize("web.form.options_placeholder"))}">{escape(field._value())}</textarea>')
        return Markup(textarea + "<script>" + script + "</script>")


_OPTIONS_SCRIPT = r"""
(function () {
  var ta = document.getElementById(__ID__);
  if (!ta) { return; }
  var T = __LABELS__;
  var box = document.createElement('div');
  var list = document.createElement('div');
  var add = document.createElement('button');
  add.type = 'button';
  add.className = 'btn btn-outline-primary';
  add.textContent = '\uFF0B ' + T.add;
  box.appendChild(list);
  box.appendChild(add);
  ta.style.display = 'none';
  ta.parentNode.insertBefore(box, ta.nextSibling);

  function field(title, input, cls) {
    var col = document.createElement('div');
    col.className = cls;
    var label = document.createElement('label');
    label.className = 'form-label';
    label.textContent = title;
    col.appendChild(label);
    col.appendChild(input);
    return {col: col, label: label};
  }
  function input(type, attrs) {
    var el = document.createElement('input');
    el.type = type;
    el.className = 'form-control';
    for (var k in attrs) { el.setAttribute(k, attrs[k]); }
    el.addEventListener('input', sync);
    return el;
  }
  function renumber() {
    var rows = list.querySelectorAll('.opt-row');
    for (var i = 0; i < rows.length; i++) {
      rows[i].querySelector('.opt-title').textContent = T.option + ' ' + (i + 1);
    }
  }
  function sync() {
    var lines = [];
    var rows = list.querySelectorAll('.opt-row');
    for (var i = 0; i < rows.length; i++) {
      var v = rows[i].querySelectorAll('input');
      var a = v[0].value.trim(), b = v[1].value.trim(), c = v[2].value.trim();
      if (a || b || c) { lines.push(a + ' | ' + b + (c !== '' ? ' | ' + c : '')); }
    }
    ta.value = lines.join('\n');
  }
  function addRow(label, price, stock) {
    var row = document.createElement('div');
    row.className = 'opt-row row g-2 align-items-end mb-2';
    var a = field(T.option, input('text', {maxlength: 32, placeholder: T.placeholder}), 'col-md-4');
    a.label.className = 'form-label opt-title';
    var b = field(T.price, input('number', {min: 0, step: '0.01'}), 'col-md-3');
    var c = field(T.stock, input('number', {min: 0, step: '1'}), 'col-md-3');
    var del = document.createElement('button');
    del.type = 'button';
    del.className = 'btn btn-outline-danger opt-del';
    del.title = T.remove;
    del.textContent = '\u00D7';
    del.addEventListener('click', function () { row.remove(); renumber(); sync(); });
    var last = document.createElement('div');
    last.className = 'col-md-2';
    last.appendChild(del);
    row.appendChild(a.col); row.appendChild(b.col); row.appendChild(c.col); row.appendChild(last);
    row.querySelectorAll('input')[0].value = label || '';
    row.querySelectorAll('input')[1].value = price || '';
    row.querySelectorAll('input')[2].value = stock || '';
    list.appendChild(row);
    renumber();
  }
  var lines = ta.value.split('\n');
  for (var i = 0; i < lines.length; i++) {
    var line = lines[i].trim();
    if (!line) { continue; }
    var p = line.split('|');
    addRow((p[0] || '').trim(), (p[1] || '').trim(), (p[2] || '').trim());
  }
  if (!list.children.length) { addRow('', '', ''); }
  add.addEventListener('click', function () {
    addRow('', '', '');
    list.querySelectorAll('.opt-row:last-child input')[0].focus();
  });
})();
"""


class GoodsForm(Form):
    """Picture controls added to the generated product form (SQLAdmin has no extra-fields hook)."""
    picture = FileField(
        "Picture",
        description="JPEG, PNG or WEBP, up to 10 MB. Stored as uploaded; shown on the product card in the bot. "
                    "Leave empty to keep the current picture.",
    )
    remove_picture = BooleanField("Remove picture", description="Tick to delete the product's current picture.")


class GoodsAdmin(TranslatedModelView, model=Goods):
    translates_description = True
    column_list = [Goods.id, Goods.name, "options_summary", "picture", Goods.price, Goods.stock,
                   Goods.sale_percent, Goods.sale_until, Goods.description, Goods.category_id]
    form_base_class = GoodsForm
    column_searchable_list = [Goods.name, Goods.name_en, Goods.name_ru, Goods.name_ro]
    column_sortable_list = [Goods.id, Goods.name, Goods.price, Goods.stock]
    # One product name (the canonical one, same in every language); descriptions stay per language.
    # "Option of" / "Option label" are declared in scaffold_form so they sit together at the end.
    form_columns = ["name"] + [f"description_{lang}" for lang in LANGS] + [
        "price", "category", "stock", "sale_percent", "sale_until"]
    name = Localized("web.model.product.one")
    name_plural = Localized("web.model.product.many")
    icon = "fa-solid fa-box"

    def _bases(self) -> tuple[str, ...]:
        return ("description",)

    @property
    def form_widget_args(self) -> dict:
        args = {k: v for k, v in _translation_widget_args(True).items() if not k.startswith("name_")}
        # Not browser-"required": an option's name is composed from its head (the checks run on save).
        args["name"] = {"placeholder": localize("web.form.product_name_hint"), "required": False}
        for lang in LANGS:
            args[f"description_{lang}"]["required"] = False
        return args

    @property
    def form_args(self) -> dict:
        optional_descriptions = {f"description_{lang}": {"validators": [WtfOptional()]} for lang in LANGS}
        translation_args = {k: v for k, v in _translation_form_args(True).items() if not k.startswith("name_")}
        return {
            **{k: {**v, **optional_descriptions.get(k, {})} for k, v in translation_args.items()},
            "name": {"description": localize("web.form.product_name_hint"),
                     "validators": [WtfOptional(), _name_length_validator(_viewer_language())]},
            "stock": {"description": localize("web.form.stock_hint")},
            "sale_percent": {"description": localize("web.form.sale_percent_hint")},
            "sale_until": {"description": localize("web.form.sale_until_hint")},
        }

    async def _apply_translations(self, data: dict, model: Any, is_created: bool) -> None:
        """One name for every language (an option's name is composed from its head and already set)."""
        variant_of = data["variant_of"] if "variant_of" in data else getattr(model, "variant_of", None)
        if variant_of is None and ("name" in data or is_created):
            name = clean_name(data.get("name"))
            if not name:
                raise ValueError(localize("web.form.name_required_single"))
            if len(name) > MAX_NAME_LEN:
                raise ValueError(localize("web.form.tr_too_long_name", language=localize(f"web.form.lang.{_viewer_language()}"), limit=MAX_NAME_LEN))
            await self._check_name_free(name, model)
            data["name"] = name
            if is_created or name != getattr(model, "name", None):
                for lang in LANGS:            # a rename resets the per-language names to the new one
                    data[f"name_{lang}"] = name
        await super()._apply_translations(data, model, is_created)

    async def scaffold_form(self, *args, **kwargs):
        """Category dropdown with subcategory paths, the weight options block and the picture controls."""
        Base = await super().scaffold_form(*args, **kwargs)
        viewer = _viewer_language()

        # Description of the admin's own language right under the name, then the others.
        _own_language_first(Base, ("description",), viewer)

        async with Database().session() as session:
            categories = (await session.execute(sa_select(Categories))).scalars().all()
        by_id = {c.id: c for c in categories}
        parents = {c.parent_id for c in categories if c.parent_id}
        choices = []
        for c in categories:
            if c.id in parents:        # a category with subcategories holds no products
                continue
            label = pick(c, "name", viewer)
            if c.parent_id in by_id:
                label = f"{pick(by_id[c.parent_id], 'name', viewer)} \u203a {label}"
            choices.append((str(c.id), label))
        choices.sort(key=lambda item: item[1].casefold())

        def coerce_category(value):
            if value is None or value in ("", "None"):
                return None
            return str(getattr(value, "id", value))

        category_field = SelectField(localize("web.col.category"), choices=choices, coerce=coerce_category,
                                     validate_choice=False, render_kw={"class": "form-select"})
        category_field.creation_counter = Base.category.creation_counter if hasattr(Base, "category") else 10_000

        class LocalizedGoodsForm(Base):
            category = category_field
            options_text = TextAreaField(localize("web.col.options_text"), validators=[WtfOptional()],
                                         description=localize("web.form.options_hint"), widget=OptionsWidget())
            picture = FileField(localize("web.col.picture"), description=localize("web.form.picture_hint"))
            remove_picture = BooleanField(localize("web.form.remove_picture"),
                                          description=localize("web.form.remove_picture_hint"))

        return LocalizedGoodsForm

    def list_query(self, request: Request):
        """Weight options are managed inside their product, not listed as products of their own."""
        return sa_select(Goods).where(Goods.variant_of.is_(None))

    async def get_object_for_edit(self, value: Any) -> Any:
        obj = await super().get_object_for_edit(value)
        if obj is not None and getattr(obj, "variant_of", None) is None:
            async with Database().session() as session:
                options = (await session.execute(
                    sa_select(Goods).where(Goods.variant_of == obj.id))).scalars().all()
            obj.options_text = format_options_text(options)
        return obj

    async def list(self, request: Request):
        pagination = await super().list(request)
        with_pictures = await items_with_images()
        ids = [row.id for row in pagination.rows]
        summaries: dict[int, list[str]] = {}
        if ids:
            async with Database().session() as session:
                options = (await session.execute(
                    sa_select(Goods).where(Goods.variant_of.in_(ids)).order_by(Goods.id))).scalars().all()
            for o in options:
                summaries.setdefault(o.variant_of, []).append(f"{o.variant_label}: {plain_price(o.price)} / {o.stock}")
        for row in pagination.rows:
            row.picture = row.name in with_pictures
            row.options_summary = "; ".join(summaries.get(row.id, []))
        return pagination

    async def get_list_value(self, obj: Any, prop: str):
        if prop == "name":
            return getattr(obj, "name", None), pick(obj, "name", _viewer_language())
        if prop == "options_summary":
            text = getattr(obj, "options_summary", "") or ""
            return text, text or "\u2014"
        if prop == "picture":
            has = bool(getattr(obj, "picture", False))
            return has, (localize("web.yes") if has else "\u2014")
        return await super().get_list_value(obj, prop)

    async def on_model_change(self, data: dict, model: Any, is_created: bool, request: Request) -> None:
        # The model still holds the stock from before the edit here; remember it for the restock check.
        request.state.stock_before = 0 if is_created else int(getattr(model, "stock", 0) or 0)
        # Likewise the pre-edit name (model is not mutated yet), so a rename can drop the old name's caches.
        request.state.item_old_name = None if is_created else getattr(model, "name", None)
        request.state.item_old_category_id = None if is_created else getattr(model, "category_id", None)
        head = await self._validate_variant(data, model, is_created)
        if head is not None:
            self._name_option(data, head)
        await self._apply_translations(data, model, is_created)
        if head is not None:
            data["description"] = ""
            for lang in LANGS:
                data[f"description_{lang}"] = None

        await self._prepare_options(data, model, is_created, request, is_option=head is not None)

        # The picture controls are not columns of the product: take them out of `data` so SQLAdmin does not
        # try to set them on the model, and check the upload before anything is saved.
        upload = data.pop("picture", None)
        remove = bool(data.pop("remove_picture", False))
        content = b""
        if upload is not None and hasattr(upload, "read"):
            content = await upload.read()
        if content and remove:
            raise ValueError(localize("web.picture.err.both"))
        if content:
            try:
                validate_image(content)
            except ImageError as e:
                raise ValueError(_picture_error(e.code))
        request.state.picture_upload = content or None
        request.state.picture_remove = remove

    async def _prepare_options(self, data: dict, model: Any, is_created: bool, request: Request,
                               *, is_option: bool) -> None:
        """Parse and check the options block (it is not a column); it is applied once the product row exists."""
        text = data.pop("options_text", None)
        request.state.options_rows = None
        if text is None or is_option or getattr(model, "variant_of", None) is not None:
            return
        try:
            rows = parse_options_text(text)
            own_id = None if is_created else getattr(model, "id", None)
            await check_option_names_free(data.get("name") or getattr(model, "name", ""), own_id, rows)
        except OptionsError as e:
            raise ValueError(localize(f"web.form.options_{e.code}", **e.params))
        request.state.options_rows = rows

    async def _validate_variant(self, data: dict, model: Any, is_created: bool) -> dict | None:
        """Check the weight-option fields; returns the head's data when this product is an option.

        An option needs an existing head that is not itself an option, a label (unique per head, no ``·``),
        and takes its head's category. A product that has options cannot become one.
        """
        own_id = None if is_created else getattr(model, "id", None)
        head_id = data["variant_of"] if "variant_of" in data else getattr(model, "variant_of", None)
        raw_label = data["variant_label"] if "variant_label" in data else getattr(model, "variant_label", None)
        label = clean_name(raw_label)
        if not head_id:
            if label:
                raise ValueError(localize("web.form.variant_label_no_head"))
            data["variant_of"] = None
            if "variant_label" in data:
                data["variant_label"] = None
            return None
        head_id = int(head_id)
        async with Database().session() as session:
            head = await session.get(Goods, head_id)
            if head is None:
                raise ValueError(localize("web.form.variant_head_unknown"))
            if head.id == own_id:
                raise ValueError(localize("web.form.variant_head_self"))
            if head.variant_of is not None:
                raise ValueError(localize("web.form.variant_head_is_option"))
            if own_id is not None and (await session.execute(
                    sa_select(Goods.id).where(Goods.variant_of == own_id).limit(1))).first() is not None:
                raise ValueError(localize("web.form.variant_has_options"))
            if not label:
                raise ValueError(localize("web.form.variant_label_required"))
            if "\u00b7" in label:
                raise ValueError(localize("web.form.variant_label_bad"))
            if len(label) > 32:
                raise ValueError(localize("web.form.variant_label_too_long"))
            clash = sa_select(Goods.id).where(Goods.variant_of == head.id,
                                              sa_func.lower(Goods.variant_label) == label.lower())
            if own_id is not None:
                clash = clash.where(Goods.id != own_id)
            if (await session.execute(clash.limit(1))).first() is not None:
                raise ValueError(localize("web.form.variant_label_taken", label=label))
            head_data = {c: getattr(head, c) for c in (
                "id", "name", "category_id", *[f"name_{l}" for l in LANGS])}
        data["variant_of"] = head_id
        data["variant_label"] = label
        data["category"] = str(head_data["category_id"])
        return head_data

    def _name_option(self, data: dict, head: dict) -> None:
        """An option is named "<head> · <label>" (per language too) and has no description of its own:
        the product card shows the head's. The typed name and description are replaced (the description
        is cleared after the translations are checked)."""
        label = data["variant_label"]
        main = i18n_main.get_locale()
        canonical = f"{head['name']} \u00b7 {label}"
        if len(canonical) > MAX_NAME_LEN:
            raise ValueError(localize("web.form.variant_name_too_long", limit=MAX_NAME_LEN))
        for lang in LANGS:
            base = head.get(f"name_{lang}")
            data[f"name_{lang}"] = f"{base} \u00b7 {label}"[:MAX_NAME_LEN] if base else None
            data[f"description_{lang}"] = None
        data["name"] = canonical
        data[f"name_{main}"] = canonical
        viewer = _viewer_language()
        if not data.get(f"name_{viewer}"):
            data[f"name_{viewer}"] = canonical
        data[f"description_{viewer}"] = "-"       # satisfies the required-description check; cleared after

    async def _invalidate(self, model: Any, old_name: str | None = None) -> None:
        # The translations ride in the cached `item_info:<name>` row; on a rename the old name's entries
        # (info, values, image, rating) must go too.
        for name in {n for n in (getattr(model, "name", None), old_name) if n}:
            safe_create_task(invalidate_item_cache(name))
        category_id = getattr(model, "category_id", None)
        if category_id:
            async with Database().session() as session:
                category = (await session.execute(
                    sa_select(Categories.name).where(Categories.id == category_id))).scalar()
            if category:
                safe_create_task(invalidate_category_cache(category))

    async def _follow_head_category(self, model: Any, old_category_id: int | None) -> None:
        """Moving a head to another category moves its options with it."""
        if getattr(model, "variant_of", None) is not None or model.id is None or old_category_id == model.category_id:
            return
        async with Database().session() as session:
            names = (await session.execute(
                sa_select(Goods.name).where(Goods.variant_of == model.id))).scalars().all()
            if names:
                await session.execute(
                    sa_update(Goods).where(Goods.variant_of == model.id).values(category_id=model.category_id))
        for name in names:
            safe_create_task(invalidate_item_cache(name))

    async def after_model_change(self, data: dict, model: Any, is_created: bool, request: Request) -> None:
        await super().after_model_change(data, model, is_created, request)
        await self._invalidate(model, getattr(request.state, "item_old_name", None))
        if not is_created:
            await self._follow_head_category(model, getattr(request.state, "item_old_category_id", None))

        name = getattr(model, "name", None)
        stock_before = getattr(request.state, "stock_before", None)
        if name and stock_before == 0 and (getattr(model, "stock", 0) or 0) > 0 and _notifier_bot is not None:
            safe_create_task(notify_restock(_notifier_bot, name))

        rows = getattr(request.state, "options_rows", None)
        if isinstance(rows, list) and getattr(model, "id", None) is not None:
            result = await sync_item_options(model.id, rows)
            if _notifier_bot is not None:
                for option_name in result["restocked"]:
                    safe_create_task(notify_restock(_notifier_bot, option_name))

        await self._apply_picture(model, request)

    async def _apply_picture(self, model: Any, request: Request) -> None:
        """Store or drop the picture once the product row exists (a new product has no id before the commit)."""
        name = getattr(model, "name", None)
        upload = getattr(request.state, "picture_upload", None)
        remove = getattr(request.state, "picture_remove", False) is True
        if not isinstance(upload, bytes):
            upload = None
        if not name or not (upload or remove):
            return
        if upload:
            ok, code = await set_item_image(name, upload)
            if not ok:
                raise ValueError(_picture_error(code))
            action = "set"
        else:
            action = "remove" if await remove_item_image(name) else None
        if action:
            await log_audit(
                "sqladmin_update_item_photo", resource_type=type(self).name, resource_id=str(getattr(model, "id", name)),
                details=f"item={name}, action={action}", ip_address=_client_ip(request),
            )

    async def on_model_delete(self, model: Any, request: Request) -> None:
        """A head takes its weight options with it, exactly as the bot's delete does (SQLAdmin deletes
        through the ORM, which knows nothing of the options)."""
        async with Database().session() as session:
            names = (await session.execute(
                sa_select(Goods.name).where(Goods.variant_of == model.id))).scalars().all()
        for name in names:
            await delete_item(name)

    async def after_model_delete(self, model: Any, request: Request) -> None:
        await super().after_model_delete(model, request)
        await self._invalidate(model)


async def apply_order_action(action_name: str, order_id: int) -> tuple[bool, str]:
    """Run one order action through the same code as the bot, then tell the customer.

    Status changes and payment checks go through ``orders.py`` so stock, balance refunds and
    referral commissions are never bypassed. Returns ``(ok, code)``; a refused move is skipped.
    """
    if action_name == "payment_confirmed":
        ok, code, order = await confirm_mia_payment(order_id)
    else:
        ok, code, order = await set_order_status(order_id, action_name)
    if ok and order is not None:
        await log_audit(
            f"sqladmin_order_{action_name}", resource_type="Order", resource_id=str(order_id),
            details=f"payment={order['payment_status']}",
        )
        if _notifier_bot is not None:
            await notify_customer(_notifier_bot, order, action_name)
            for name in order.get("restocked", []):
                safe_create_task(notify_restock(_notifier_bot, name))
    else:
        await log_audit(
            "sqladmin_order_action_refused", level="WARNING", resource_type="Order",
            resource_id=str(order_id), details=f"action={action_name}, code={code}",
        )
    return ok, code


class OrderAdmin(LocalizedModelView, model=Orders):
    """Orders are read-only here; status changes are actions that reuse the bot's own order logic."""
    column_list = [Orders.id, Orders.user_id, Orders.status, Orders.payment_method, Orders.payment_status,
                   Orders.fulfillment, Orders.customer_name, Orders.phone, Orders.total,
                   Orders.balance_used, Orders.created_at]
    column_details_list = [Orders.id, Orders.user_id, Orders.status, Orders.payment_method,
                           Orders.payment_status, Orders.fulfillment, Orders.customer_name,
                           Orders.phone, Orders.address, Orders.comment, Orders.total,
                           Orders.balance_used, Orders.pay_by, Orders.created_at, Orders.updated_at,
                           Orders.items]
    # status / payment_status / payment_method are searchable too, which doubles as the filter.
    column_searchable_list = [Orders.customer_name, Orders.phone, Orders.user_id, Orders.status,
                              Orders.payment_status, Orders.payment_method, Orders.fulfillment]
    column_sortable_list = [Orders.id, Orders.created_at, Orders.total, Orders.status]
    column_default_sort = (Orders.id, True)
    can_create = False
    can_edit = False
    can_delete = False
    details_template = "order_details.html"
    name = Localized("web.model.order.one")
    name_plural = Localized("web.model.order.many")
    icon = "fa-solid fa-box-open"

    @staticmethod
    def available_actions(order) -> list[str]:
        """The actions that make sense for this order right now (the details page shows only these)."""
        status = getattr(order, "status", None)
        if status not in OrderStatus.ACTIVE:
            return []
        actions = []
        if status == OrderStatus.NEW:
            if order.payment_method == PaymentMethod.MIA and order.payment_status in (
                    PaymentStatus.AWAITING_PAYMENT, PaymentStatus.AWAITING_CONFIRMATION):
                actions.append("confirm-payment")   # SQLAdmin turns "_" into "-" in action names
            else:
                actions.append("confirm")
        elif status == OrderStatus.CONFIRMED:
            actions += ["ship", "complete"]
        elif status == OrderStatus.SHIPPED:
            actions.append("complete")
        actions.append("cancel")
        return actions

    async def _run(self, request: Request, action_name: str) -> RedirectResponse:
        pks = [int(p) for p in request.query_params.get("pks", "").split(",") if p.strip().isdigit()]
        for order_id in pks:
            await apply_order_action(action_name, order_id)
        return RedirectResponse(request.url_for("admin:list", identity=self.identity), status_code=302)

    @action(name="confirm_payment", label=LazyText("web.action.confirm_payment"),
            confirmation_message=LazyText("web.action.confirm_payment.ask"),
            add_in_detail=True, add_in_list=True)
    async def confirm_payment(self, request: Request):
        return await self._run(request, "payment_confirmed")

    @action(name="confirm", label=LazyText("web.action.confirm"),
            confirmation_message=LazyText("web.action.confirm.ask"),
            add_in_detail=True, add_in_list=True)
    async def confirm_order(self, request: Request):
        return await self._run(request, OrderStatus.CONFIRMED)

    @action(name="ship", label=LazyText("web.action.ship"),
            confirmation_message=LazyText("web.action.ship.ask"),
            add_in_detail=True, add_in_list=True)
    async def ship_order(self, request: Request):
        return await self._run(request, OrderStatus.SHIPPED)

    @action(name="complete", label=LazyText("web.action.complete"),
            confirmation_message=LazyText("web.action.complete.ask"),
            add_in_detail=True, add_in_list=True)
    async def complete_order(self, request: Request):
        return await self._run(request, OrderStatus.COMPLETED)

    @action(name="cancel", label=LazyText("web.action.cancel"),
            confirmation_message=LazyText("web.action.cancel.ask"),
            add_in_detail=True, add_in_list=True)
    async def cancel_order(self, request: Request):
        return await self._run(request, OrderStatus.CANCELLED)


class OrderItemsAdmin(LocalizedModelView, model=OrderItems):
    column_list = [OrderItems.id, OrderItems.order_id, OrderItems.item_name, OrderItems.quantity,
                   OrderItems.unit_price, OrderItems.line_total]
    column_searchable_list = [OrderItems.item_name, OrderItems.order_id]
    column_sortable_list = [OrderItems.id, OrderItems.order_id, OrderItems.line_total]
    column_default_sort = (OrderItems.id, True)
    can_create = False
    can_edit = False
    can_delete = False
    name = Localized("web.model.order_line.one")
    name_plural = Localized("web.model.order_line.many")
    icon = "fa-solid fa-list"


class OperationsAdmin(LocalizedModelView, model=Operations):
    column_list = [Operations.id, Operations.user_id, Operations.operation_value,
                   Operations.operation_time]
    column_searchable_list = [Operations.user_id]
    column_sortable_list = [Operations.id, Operations.operation_time, Operations.operation_value]
    column_default_sort = (Operations.id, True)
    can_create = False
    can_edit = False
    can_delete = False
    name = Localized("web.model.operation.one")
    name_plural = Localized("web.model.operation.many")
    icon = "fa-solid fa-money-bill-transfer"


class ReferralEarningsAdmin(LocalizedModelView, model=ReferralEarnings):
    column_list = [ReferralEarnings.id, ReferralEarnings.referrer_id,
                   ReferralEarnings.referral_id, ReferralEarnings.amount,
                   ReferralEarnings.original_amount, ReferralEarnings.created_at]
    column_searchable_list = [ReferralEarnings.referrer_id, ReferralEarnings.referral_id]
    column_sortable_list = [ReferralEarnings.id, ReferralEarnings.created_at, ReferralEarnings.amount]
    column_default_sort = (ReferralEarnings.id, True)
    can_create = False
    can_edit = False
    can_delete = False
    name = Localized("web.model.referral_earning.one")
    name_plural = Localized("web.model.referral_earning.many")
    icon = "fa-solid fa-handshake"


class AuditLogAdmin(LocalizedModelView, model=AuditLog):
    column_list = [AuditLog.id, AuditLog.timestamp, AuditLog.level, AuditLog.user_id,
                   AuditLog.action, AuditLog.resource_type, AuditLog.resource_id,
                   AuditLog.details, AuditLog.ip_address]
    column_searchable_list = [AuditLog.action, AuditLog.resource_type, AuditLog.details]
    column_sortable_list = [AuditLog.id, AuditLog.timestamp, AuditLog.level, AuditLog.action]
    column_default_sort = (AuditLog.id, True)
    can_create = False
    can_edit = False
    can_delete = False
    name = Localized("web.model.audit_log.one")
    name_plural = Localized("web.model.audit_log.many")
    icon = "fa-solid fa-clipboard-list"


def _format_promo_scope_html(model, name):
    """Render scope, flagging a promo whose bound category/item was deleted.
    """
    scope = getattr(model, name, None) or "global"
    dangling = (
        (scope == "category" and getattr(model, "category_id", None) is None)
        or (scope == "item" and getattr(model, "item_id", None) is None)
    )
    if not dangling:
        return Markup(
            f'<span style="display:inline-block;background:#e2e8f0;padding:1px 6px;'
            f'border-radius:4px;font-size:11px">{escape(scope)}</span>'
        )
    return Markup(
        f'<span style="display:inline-block;background:#e2e8f0;padding:1px 6px;'
        f'border-radius:4px;font-size:11px">{escape(scope)}</span> '
        f'<span style="display:inline-block;background:#fed7d7;color:#9b2c2c;'
        f'padding:1px 6px;border-radius:4px;font-size:11px;font-weight:600" '
        f'title="{escape(localize("web.promo.dangling_hint"))}">'
        f'{escape(localize("web.promo.dangling"))}</span>'
    )


class PromoCodeAdmin(AuditModelView, model=PromoCodes):
    column_list = [PromoCodes.id, PromoCodes.code, PromoCodes.discount_type,
                   PromoCodes.discount_value, PromoCodes.scope, PromoCodes.category_id,
                   PromoCodes.item_id, PromoCodes.max_uses, PromoCodes.current_uses,
                   PromoCodes.is_active, PromoCodes.expires_at, PromoCodes.created_at]
    column_searchable_list = [PromoCodes.code]
    column_sortable_list = [PromoCodes.id, PromoCodes.code, PromoCodes.created_at]
    column_default_sort = (PromoCodes.id, True)
    form_columns = [PromoCodes.code, PromoCodes.discount_type, PromoCodes.discount_value,
                    PromoCodes.scope, PromoCodes.max_uses, PromoCodes.expires_at, PromoCodes.is_active]
    form_overrides = {"discount_type": SelectField, "scope": SelectField}
    @property
    def form_args(self) -> dict:
        return {
            "discount_type": {
                "choices": [
                    ("percent", localize("web.promo.type_percent")),
                    ("fixed", localize("web.promo.type_fixed")),
                    ("balance", localize("web.promo.type_balance")),
                ],
                "description": localize("web.promo.type_hint"),
            },
            "scope": {
                "choices": [
                    ("global", localize("web.promo.scope_global")),
                    ("category", localize("web.promo.scope_category")),
                    ("item", localize("web.promo.scope_item")),
                ],
                "description": localize("web.promo.scope_hint"),
            },
        }

    column_formatters = {"scope": _format_promo_scope_html}
    column_formatters_detail = {"scope": _format_promo_scope_html}
    name = Localized("web.model.promo_code.one")
    name_plural = Localized("web.model.promo_code.many")
    icon = "fa-solid fa-tag"

    async def scaffold_form(self, *args, **kwargs):
        """Add Category / Item as dropdowns of real records."""
        Form = await super().scaffold_form(*args, **kwargs)

        async with self.session_maker() as s:
            cats = (await s.execute(
                sa_select(Categories.id, Categories.name).order_by(Categories.name)
            )).all()
            items = (await s.execute(
                sa_select(Goods.id, Goods.name).order_by(Goods.name)
            )).all()

        none_label = localize("web.promo.none_global")
        cat_choices = [("", none_label)] + [(str(cid), name) for cid, name in cats]
        item_choices = [("", none_label)] + [(str(gid), name) for gid, name in items]

        def _coerce(v):
            return int(v) if v not in (None, "", "None") else None

        class PromoFormWithBindings(Form):
            category_id = SelectField(
                localize("web.promo.category"), choices=cat_choices, coerce=_coerce,
                validators=[WtfOptional()],
                description=localize("web.promo.category_hint"),
            )
            item_id = SelectField(
                localize("web.promo.item"), choices=item_choices, coerce=_coerce,
                validators=[WtfOptional()],
                description=localize("web.promo.item_hint"),
            )

        return PromoFormWithBindings

    async def on_model_change(self, data: dict, model: Any, is_created: bool, request: Request) -> None:
        """Validate/normalize a promo before persisting."""
        code = (data.get("code") or "").strip().upper()
        if not code:
            raise ValueError(localize("web.promo.err.code_required"))
        data["code"] = code

        dtype = data.get("discount_type")
        if dtype not in ("percent", "fixed", "balance"):
            raise ValueError(localize("web.promo.err.bad_type"))

        try:
            dval = Decimal(str(data.get("discount_value")))
        except (InvalidOperation, TypeError):
            raise ValueError(localize("web.promo.err.value_not_number"))
        if dval < 0:
            raise ValueError(localize("web.promo.err.value_negative"))
        if dtype == "percent" and dval > 100:
            raise ValueError(localize("web.promo.err.percent_range"))

        # The SelectFields coerce to int or None; normalize anything else too.
        def _as_id(v):
            if v in (None, "", "None"):
                return None
            try:
                return int(v)
            except (TypeError, ValueError):
                return None

        category_id = _as_id(data.get("category_id"))
        item_id = _as_id(data.get("item_id"))
        data["category_id"] = category_id
        data["item_id"] = item_id

        if category_id is not None and item_id is not None:
            raise ValueError(localize("web.promo.err.both_bound"))

        scope = (data.get("scope") or "global").strip()
        expected = promo_scope_for(category_id, item_id)
        if scope != expected:
            raise ValueError(localize("web.promo.err.scope_mismatch", scope=scope, expected=expected))


class CartItemsAdmin(LocalizedModelView, model=CartItems):
    column_list = [CartItems.id, CartItems.user_id, CartItems.item_id, CartItems.added_at]
    column_searchable_list = [CartItems.user_id, CartItems.item_id]
    column_sortable_list = [CartItems.id, CartItems.added_at]
    column_default_sort = (CartItems.id, True)
    can_create = False
    can_edit = False
    can_delete = False
    name = Localized("web.model.cart_item.one")
    name_plural = Localized("web.model.cart_item.many")
    icon = "fa-solid fa-cart-plus"



class ReviewsAdmin(AuditModelView, model=Reviews):
    column_list = [Reviews.id, Reviews.user_id, Reviews.item_id,
                   Reviews.rating, Reviews.text, Reviews.created_at]
    column_searchable_list = [Reviews.user_id, Reviews.item_id]
    column_sortable_list = [Reviews.id, Reviews.rating, Reviews.created_at]
    column_default_sort = (Reviews.id, True)
    name = Localized("web.model.review.one")
    name_plural = Localized("web.model.review.many")
    icon = "fa-solid fa-star"

    async def _invalidate(self, model: Any) -> None:
        # avg_rating is cached for 600s and keyed by product name, so editing a rating here would otherwise not show up in the bot until it expires.
        item_id = getattr(model, "item_id", None)
        if item_id is None:
            return
        name = await get_item_name_by_id(int(item_id))
        if name:
            safe_create_task(invalidate_rating_cache(name))

    async def after_model_change(self, data: dict, model: Any, is_created: bool, request: Request) -> None:
        await super().after_model_change(data, model, is_created, request)
        await self._invalidate(model)

    async def after_model_delete(self, model: Any, request: Request) -> None:
        await super().after_model_delete(model, request)
        await self._invalidate(model)


# Health & Metrics Endpoints
async def _signed_in(request: Request) -> bool:
    try:
        return await current_web_user(request) is not None
    except Exception as e:  # the database being down must not break the health probe
        logger.error(f"Panel session check failed: {e}")
        return False


async def health_check(request: Request) -> JSONResponse:
    db_ok = True
    try:
        async with Database().session() as s:
            await s.execute(text("SELECT 1"))
    except Exception as e:
        logger.error(f"Health check database error: {e}")
        db_ok = False

    status_code = 200 if db_ok else 503
    if not await _signed_in(request):
        return JSONResponse(
            {"status": "healthy" if db_ok else "unhealthy"},
            status_code=status_code,
        )

    # Authenticated operators get the full diagnostic view.
    health_status = {
        "status": "healthy" if db_ok else "unhealthy",
        "checks": {"database": "ok" if db_ok else "error"},
    }

    cache = get_cache_manager()
    if cache:
        health_status["checks"]["redis"] = "ok" if cache._healthy else "degraded"
    else:
        health_status["checks"]["redis"] = "not configured"

    metrics = get_metrics()
    if metrics:
        health_status["checks"]["metrics"] = "ok"
        health_status["uptime"] = metrics.get_metrics_summary()["uptime_seconds"]

    return JSONResponse(health_status, status_code=status_code)


async def prometheus_metrics(request: Request) -> PlainTextResponse:
    if not await _signed_in(request):
        return PlainTextResponse("Unauthorized", status_code=401)
    metrics = get_metrics()
    if not metrics:
        return PlainTextResponse("# Metrics not initialized\n", status_code=503)
    return PlainTextResponse(metrics.export_to_prometheus(), media_type="text/plain")


async def metrics_json(request: Request) -> JSONResponse:
    if not await _signed_in(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    metrics = get_metrics()
    if not metrics:
        return JSONResponse({"error": "Metrics not initialized"}, status_code=503)
    return JSONResponse(metrics.get_metrics_summary(), status_code=200)


# App Factory
def create_admin_app(bot: Any = None) -> Starlette:
    """Build the admin panel app."""
    set_notifier_bot(bot)

    from bot.web.export import export_routes

    async def root_redirect(request: Request) -> RedirectResponse:
        return RedirectResponse(url="/admin")

    routes = [
        Route("/", root_redirect),
        Route("/health", health_check),
        Route("/metrics", metrics_json),
        Route("/metrics/prometheus", prometheus_metrics),
    ] + export_routes

    from bot.web.accounts import MyAccountView, WebUserAdmin

    app = Starlette(routes=routes)
    # Added first so it ends up inside SessionMiddleware: it reads the language out of the session.
    app.add_middleware(LanguageMiddleware)
    app.add_middleware(
        SessionMiddleware,
        secret_key=EnvKeys.SECRET_KEY,
        max_age=1800,
        https_only=EnvKeys.session_cookie_secure(),
        same_site="strict",
    )

    auth_backend = AdminAuth(secret_key=EnvKeys.SECRET_KEY)
    admin = Admin(
        app,
        engine=Database().engine,
        authentication_backend=auth_backend,
        title="Telegram Shop Admin",
        # Our own login, layout and help pages replace SQLAdmin's.
        templates_dir=os.path.join(os.path.dirname(__file__), "templates"),
    )
    env = admin.templates.env
    env.globals["_"] = localize
    env.globals["languages"] = LANGUAGES
    env.globals["current_language"] = current_language
    env.globals["error_text"] = error_text
    env.globals["main_language_name"] = lambda: localize(f"web.form.lang.{i18n_main.get_locale()}")

    admin.add_view(UserAdmin)
    admin.add_view(RoleAdmin)
    admin.add_view(CategoryAdmin)
    admin.add_view(GoodsAdmin)
    admin.add_view(OrderAdmin)
    admin.add_view(OrderItemsAdmin)
    admin.add_view(OperationsAdmin)
    admin.add_view(ReferralEarningsAdmin)
    admin.add_view(AuditLogAdmin)
    admin.add_view(PromoCodeAdmin)
    admin.add_view(CartItemsAdmin)
    if EnvKeys.REVIEWS_ENABLED == "1":
        admin.add_view(ReviewsAdmin)
    admin.add_view(WebUserAdmin)
    admin.add_view(MyAccountView)

    return app
