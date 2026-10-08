"""Web-panel accounts: lookup, create, bootstrap. Passwords are always stored hashed."""
import logging
from datetime import datetime, timezone

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError

from bot.database import Database
from bot.database.models.main import WebUsers, WebRole
from bot.web.passwords import hash_password, check_password_strength

logger = logging.getLogger(__name__)

LANGS = ("en", "ru", "ro")


def web_user_to_dict(u: WebUsers) -> dict:
    """Plain snapshot of an account — deliberately without the password hash."""
    return {
        "id": u.id, "username": u.username, "role": u.role, "language": u.language,
        "is_active": u.is_active, "created_at": u.created_at, "last_login_at": u.last_login_at,
        "telegram_id": u.telegram_id, "totp_enabled": bool(u.totp_enabled),
        # Enrolment started but not confirmed: the page shows the key again until it is confirmed or replaced.
        "totp_pending": bool(u.totp_secret) and not u.totp_enabled,
    }


async def get_web_user_auth(username: str) -> dict | None:
    """The account *with* its hash, for the login check only."""
    async with Database().session() as s:
        u = (await s.execute(
            select(WebUsers).where(func.lower(WebUsers.username) == (username or "").strip().lower())
        )).scalars().first()
        return None if u is None else {**web_user_to_dict(u), "password_hash": u.password_hash}


async def get_web_user(user_id: int) -> dict | None:
    async with Database().session() as s:
        u = (await s.execute(select(WebUsers).where(WebUsers.id == user_id))).scalars().first()
        return None if u is None else web_user_to_dict(u)


async def count_active_admins() -> int:
    async with Database().session() as s:
        return (await s.execute(
            select(func.count()).select_from(WebUsers)
            .where(WebUsers.role == WebRole.ADMIN, WebUsers.is_active.is_(True))
        )).scalar() or 0


async def create_web_user(username: str, password: str, role: str = WebRole.STAFF,
                          language: str | None = None, is_active: bool = True) -> tuple[bool, str]:
    """Create an account. Returns ``(ok, code)``; codes: success, invalid_username, invalid_role,
    invalid_language, password_too_short, password_too_long, username_taken."""
    username = (username or "").strip()
    if not (1 <= len(username) <= 64) or any(c.isspace() for c in username):
        return False, "invalid_username"
    if role not in WebRole.CHOICES:
        return False, "invalid_role"
    if language is not None and language not in LANGS:
        return False, "invalid_language"
    weak = check_password_strength(password or "")
    if weak:
        return False, weak
    try:
        async with Database().session() as s:
            exists = (await s.execute(
                select(WebUsers.id).where(func.lower(WebUsers.username) == username.lower())
            )).first()
            if exists:
                return False, "username_taken"
            s.add(WebUsers(username=username, password_hash=hash_password(password), role=role,
                           language=language, is_active=is_active))
    except IntegrityError:
        return False, "username_taken"
    return True, "success"


async def record_web_login(user_id: int, language: str | None = None) -> None:
    """Stamp the login; remember the language picked on the login page if the account has none."""
    async with Database().session() as s:
        u = (await s.execute(select(WebUsers).where(WebUsers.id == user_id))).scalars().first()
        if not u:
            return
        u.last_login_at = datetime.now(timezone.utc)
        if u.language is None and language in LANGS:
            u.language = language


async def set_web_user_language(user_id: int, language: str) -> bool:
    if language not in LANGS:
        return False
    async with Database().session() as s:
        u = (await s.execute(select(WebUsers).where(WebUsers.id == user_id))).scalars().first()
        if not u:
            return False
        u.language = language
    return True


async def set_web_user_telegram_id(user_id: int, telegram_id: int | None) -> bool:
    """Remember (or clear, with None) the person's Telegram ID, where their test mailings are sent."""
    if telegram_id is not None and (isinstance(telegram_id, bool) or telegram_id <= 0):
        return False
    async with Database().session() as s:
        u = (await s.execute(select(WebUsers).where(WebUsers.id == user_id))).scalars().first()
        if not u:
            return False
        u.telegram_id = telegram_id
    return True


async def set_web_user_password(user_id: int, new_password: str) -> tuple[bool, str]:
    weak = check_password_strength(new_password or "")
    if weak:
        return False, weak
    async with Database().session() as s:
        u = (await s.execute(select(WebUsers).where(WebUsers.id == user_id))).scalars().first()
        if not u:
            return False, "not_found"
        u.password_hash = hash_password(new_password)
    return True, "success"


# --- two-step sign-in ----------------------------------------------------------------------------------------------

async def get_totp(user_id: int) -> dict | None:
    """The sealed secret and what is left of the backup codes; None for an unknown account."""
    async with Database().session() as s:
        u = (await s.execute(select(WebUsers).where(WebUsers.id == user_id))).scalars().first()
        if u is None:
            return None
        return {"secret": u.totp_secret, "enabled": bool(u.totp_enabled), "last_step": u.totp_last_step,
                "backup": [h for h in (u.totp_backup or "").split(",") if h]}


async def start_totp(user_id: int, sealed_secret: str) -> bool:
    """Store a fresh (sealed) secret, still switched off. A second start replaces the first."""
    async with Database().session() as s:
        u = (await s.execute(select(WebUsers).where(WebUsers.id == user_id))).scalars().first()
        if u is None or u.totp_enabled:
            return False
        u.totp_secret = sealed_secret
        u.totp_last_step = None
    return True


async def enable_totp(user_id: int, step: int, backup_hashes: list[str]) -> bool:
    """Switch it on after the first valid code (``step``), with the backup codes."""
    async with Database().session() as s:
        u = (await s.execute(select(WebUsers).where(WebUsers.id == user_id))).scalars().first()
        if u is None or u.totp_enabled or not u.totp_secret:
            return False
        u.totp_enabled = True
        u.totp_last_step = step
        u.totp_backup = ",".join(backup_hashes)
    return True


async def disable_totp(user_id: int) -> bool:
    """Back to a password-only account (own choice, or an Admin resetting a lost phone)."""
    async with Database().session() as s:
        u = (await s.execute(select(WebUsers).where(WebUsers.id == user_id))).scalars().first()
        if u is None:
            return False
        u.totp_enabled = False
        u.totp_secret = None
        u.totp_last_step = None
        u.totp_backup = None
    return True


async def accept_totp_step(user_id: int, step: int) -> bool:
    """Remember the 30-second step a code was used in. False when that step (or a later one) was used already."""
    async with Database().session() as s:
        result = await s.execute(
            update(WebUsers).where(WebUsers.id == user_id, WebUsers.totp_enabled.is_(True),
                                   or_(WebUsers.totp_last_step.is_(None), WebUsers.totp_last_step < step))
            .values(totp_last_step=step))
        return (result.rowcount or 0) == 1


async def use_backup_code(user_id: int, code_hash: str) -> bool:
    """Spend one backup code. False when the account does not have it (or it was spent a moment ago)."""
    async with Database().session() as s:
        u = (await s.execute(select(WebUsers).where(WebUsers.id == user_id).with_for_update())).scalars().first()
        if u is None or not u.totp_enabled:
            return False
        hashes = [h for h in (u.totp_backup or "").split(",") if h]
        if code_hash not in hashes:
            return False
        hashes.remove(code_hash)
        u.totp_backup = ",".join(hashes)
    return True


async def replace_backup_codes(user_id: int, backup_hashes: list[str]) -> bool:
    async with Database().session() as s:
        u = (await s.execute(select(WebUsers).where(WebUsers.id == user_id))).scalars().first()
        if u is None or not u.totp_enabled:
            return False
        u.totp_backup = ",".join(backup_hashes)
    return True


async def bootstrap_web_admin(username: str, password: str) -> bool:
    """Create the first Admin from ADMIN_USERNAME/ADMIN_PASSWORD when no account exists yet.

    After that the env pair is only a seed: accounts live in the database. Returns True if created.
    """
    async with Database().session() as s:
        if (await s.execute(select(func.count()).select_from(WebUsers))).scalar():
            return False
    ok, code = await create_web_user(username, password, WebRole.ADMIN)
    if not ok:
        # e.g. ADMIN_PASSWORD shorter than the minimum: still let the owner in with what they configured.
        logger.warning("Bootstrap admin password rejected (%s); storing it as configured", code)
        async with Database().session() as s:
            s.add(WebUsers(username=username.strip()[:64] or "admin", password_hash=hash_password(password),
                           role=WebRole.ADMIN))
    return True
