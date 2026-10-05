"""Web-panel accounts: the Admin-only account manager and everyone's "My account" page."""
import asyncio
import logging
from typing import Any

from sqlalchemy import func, select
from sqladmin import BaseView, expose
from starlette.exceptions import HTTPException
from starlette.requests import Request
from wtforms import PasswordField, SelectField

from bot.database.main import Database
from bot.database.methods.audit import log_audit
from bot.database.methods.web_users import (
    LANGS, count_active_admins, get_web_user, get_web_user_auth,
    set_web_user_language, set_web_user_password,
)
from bot.database.models.main import WebRole, WebUsers
from bot.i18n.main import LANGUAGES, localize, use_language
from bot.web.admin import AuditModelView, _client_ip, _login_limiter
from bot.web.language import Localized
from bot.web.passwords import (
    MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH, check_password_strength, hash_password, verify_password,
)
from bot.web.session import current_web_user, session_is_admin

logger = logging.getLogger(__name__)


def _password_error(code: str) -> str:
    return localize(f"web.account.err.{code}", min=MIN_PASSWORD_LENGTH, max=MAX_PASSWORD_LENGTH)


def _forbidden() -> HTTPException:
    return HTTPException(status_code=403, detail=localize("web.account.err.forbidden"))


class WebUserAdmin(AuditModelView, model=WebUsers):
    """Create, edit, disable and delete panel accounts. Admin only; the hash is never shown or exported."""
    name = Localized("web.model.web_user.one")
    name_plural = Localized("web.model.web_user.many")
    icon = "fa-solid fa-user-lock"

    column_list = [WebUsers.id, WebUsers.username, WebUsers.role, WebUsers.language, WebUsers.is_active,
                   WebUsers.last_login_at, WebUsers.created_at]
    column_details_list = [WebUsers.id, WebUsers.username, WebUsers.role, WebUsers.language,
                           WebUsers.is_active, WebUsers.created_at, WebUsers.last_login_at]
    column_searchable_list = [WebUsers.username]
    column_sortable_list = [WebUsers.id, WebUsers.username, WebUsers.role, WebUsers.last_login_at]
    column_default_sort = (WebUsers.id, False)
    form_columns = [WebUsers.username, WebUsers.role, WebUsers.language, WebUsers.is_active]
    form_overrides = {"role": SelectField, "language": SelectField}
    can_export = False

    @property
    def form_args(self) -> dict:
        return {
            "role": {
                "choices": [(r, localize(f"web.role.{r}")) for r in WebRole.CHOICES],
                "description": localize("web.account.role_hint"),
            },
            "language": {
                "choices": [("", localize("web.language.unset"))] + [(c, n) for c, n in LANGUAGES],
                "description": localize("web.account.language_hint"),
            },
            "is_active": {"description": localize("web.account.active_hint")},
        }

    # --- access: Admin only, checked again on every operation so a Staff session gets 403 even by URL ---

    def is_accessible(self, request: Request) -> bool:
        return session_is_admin(request)

    def is_visible(self, request: Request) -> bool:
        return session_is_admin(request)

    @staticmethod
    def _require_admin(request: Request) -> None:
        if not session_is_admin(request):
            raise _forbidden()

    async def list(self, request: Request):
        self._require_admin(request)
        return await super().list(request)

    async def insert_model(self, request: Request, data: dict) -> Any:
        self._require_admin(request)
        return await super().insert_model(request, data)

    async def update_model(self, request: Request, pk: str, data: dict) -> Any:
        self._require_admin(request)
        return await super().update_model(request, pk, data)

    async def scaffold_form(self, *args, **kwargs):
        """The password box is not a column (the hash is), so it is added here, labelled per request."""
        Base = await super().scaffold_form(*args, **kwargs)
        # scaffold_form gets no request, so one hint covers both the create and the edit form.
        hint = localize("web.account.password_hint", min=MIN_PASSWORD_LENGTH)

        class AccountForm(Base):
            password = PasswordField(localize("web.account.password"), description=hint)

        return AccountForm

    # --- rules ---

    async def _username_taken(self, username: str, own_id: int | None) -> bool:
        async with Database().session() as s:
            q = select(WebUsers.id).where(func.lower(WebUsers.username) == username.lower())
            if own_id is not None:
                q = q.where(WebUsers.id != own_id)
            return (await s.execute(q)).first() is not None

    async def on_model_change(self, data: dict, model: Any, is_created: bool, request: Request) -> None:
        self._require_admin(request)
        my_id = request.session.get("uid")
        own_id = None if is_created else getattr(model, "id", None)

        # The password box is not a column: take it out of `data` whatever happens next.
        password = data.pop("password", None) or ""

        if "username" in data:
            username = str(data["username"] or "").strip()
            if not (1 <= len(username) <= 64) or any(c.isspace() for c in username):
                raise ValueError(localize("web.account.err.username_invalid"))
            if await self._username_taken(username, own_id):
                raise ValueError(localize("web.account.err.username_taken"))
            data["username"] = username

        role = data.get("role", getattr(model, "role", None) if not is_created else WebRole.STAFF)
        if role not in WebRole.CHOICES:
            raise ValueError(localize("web.account.err.role_invalid"))
        if data.get("language") and data["language"] not in LANGS:
            raise ValueError(localize("web.account.err.language_invalid"))

        if is_created and not password:
            raise ValueError(localize("web.account.err.password_required"))
        if password:
            weak = check_password_strength(password)
            if weak:
                raise ValueError(_password_error(weak))
            data["password_hash"] = await asyncio.to_thread(hash_password, password)
        request.state.web_user_password_set = bool(password)

        if not is_created:
            is_active = bool(data.get("is_active", model.is_active))
            if model.id == my_id:
                if not is_active:
                    raise ValueError(localize("web.account.err.cannot_deactivate_self"))
                if role != WebRole.ADMIN:
                    raise ValueError(localize("web.account.err.cannot_demote_self"))
            was_active_admin = model.role == WebRole.ADMIN and model.is_active
            if was_active_admin and (not is_active or role != WebRole.ADMIN) and await count_active_admins() <= 1:
                raise ValueError(localize("web.account.err.last_admin"))

    async def after_model_change(self, data: dict, model: Any, is_created: bool, request: Request) -> None:
        self._require_admin(request)
        await super().after_model_change(data, model, is_created, request)
        if getattr(request.state, "web_user_password_set", False) is True:
            await log_audit(
                "sqladmin_web_user_password_set", resource_type=type(self).name, resource_id=str(model.id),
                details=f"by={request.session.get('uid')}", ip_address=_client_ip(request),
            )

    async def delete_model(self, request: Request, pk: Any) -> None:
        self._require_admin(request)
        target = await get_web_user(int(pk)) if str(pk).isdigit() else None
        if target is not None:
            if target["id"] == request.session.get("uid"):
                raise HTTPException(status_code=400, detail=localize("web.account.err.cannot_delete_self"))
            if target["role"] == WebRole.ADMIN and target["is_active"] and await count_active_admins() <= 1:
                raise HTTPException(status_code=400, detail=localize("web.account.err.last_admin"))
        await super().delete_model(request, pk)

    async def on_model_delete(self, model: Any, request: Request) -> None:
        self._require_admin(request)

    async def after_model_delete(self, model: Any, request: Request) -> None:
        self._require_admin(request)
        await super().after_model_delete(model, request)


class MyAccountView(BaseView):
    """Every signed-in person: change your own password and your own panel language."""
    name = Localized("web.model.my_account")
    icon = "fa-solid fa-user-gear"

    @expose("/my-account", methods=["GET", "POST"], identity="my-account")
    async def my_account(self, request: Request):
        user = await current_web_user(request)
        if user is None:  # login_required has just checked; this is only a belt-and-braces guard
            raise HTTPException(status_code=401)

        message = error = None
        lang_override = None
        if request.method == "POST":
            form = await request.form()
            which = form.get("form")
            if which == "password":
                message, error = await self._change_password(request, user, form)
            elif which == "language":
                lang = str(form.get("language") or "")
                if await set_web_user_language(user["id"], lang):
                    request.session["lang"] = lang
                    lang_override = lang
                    # The page is rendered in the language just picked, not the one it was requested in.
                    with use_language(lang):
                        message = localize("web.my.language_saved")
                    user = {**user, "language": lang}
                else:
                    error = localize("web.account.err.language_invalid")

        context = {"user": user, "message": message, "error": error, "title": localize("web.my.title")}
        if lang_override:
            with use_language(lang_override):
                context["title"] = localize("web.my.title")
                return await self.templates.TemplateResponse(request, "my_account.html", context)
        return await self.templates.TemplateResponse(request, "my_account.html", context,
                                                     status_code=400 if error else 200)

    async def _change_password(self, request: Request, user: dict, form) -> tuple[str | None, str | None]:
        ip = _client_ip(request)
        if _login_limiter.is_blocked(ip):
            await log_audit("web_login_blocked", level="WARNING", details=f"ip={ip}, where=password_change",
                            ip_address=ip)
            return None, localize("web.my.err.wrong_current")
        current = str(form.get("current_password") or "")
        new = str(form.get("new_password") or "")
        again = str(form.get("confirm_password") or "")

        account = await get_web_user_auth(user["username"])
        if account is None or not await asyncio.to_thread(verify_password, current, account["password_hash"]):
            _login_limiter.record_failure(ip)
            await log_audit("web_password_change_failed", level="WARNING", details=f"user={user['username']}",
                            ip_address=ip)
            return None, localize("web.my.err.wrong_current")
        if new != again:
            return None, localize("web.my.err.mismatch")
        weak = check_password_strength(new)
        if weak:
            return None, _password_error(weak)
        if new == current:
            return None, localize("web.my.err.same")
        ok, _ = await set_web_user_password(user["id"], new)
        if not ok:
            return None, localize("web.my.err.generic")
        await log_audit("web_password_changed", details=f"user={user['username']}", ip_address=ip)
        return localize("web.my.password_changed"), None
