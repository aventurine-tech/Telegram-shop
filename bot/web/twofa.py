"""The second step of signing in: a code from the authenticator app, or a one-time backup code."""
import logging

from bot.database.methods.audit import log_audit
from bot.database.methods.web_users import accept_totp_step, get_totp, use_backup_code
from bot.web import totp

logger = logging.getLogger(__name__)


async def verify_second_step(user_id: int, code: str, ip: str | None = None) -> str | None:
    """``"totp"`` or ``"backup"`` when the code is good (and is now spent), else None.

    An app code works once: the 30-second step it belongs to is remembered, so a code seen over a shoulder or in a log
    cannot be replayed. A backup code works once, then is gone.
    """
    state = await get_totp(user_id)
    if state is None or not state["enabled"]:
        return None
    code = (code or "").strip()
    if totp.looks_like_backup(code):
        if await use_backup_code(user_id, totp.backup_hash(code)):
            left = len((await get_totp(user_id) or {}).get("backup", []))
            await log_audit("web_login_backup_code", level="WARNING", details=f"uid={user_id}, left={left}",
                            ip_address=ip)
            return "backup"
        return None
    secret = totp.unseal(state["secret"])
    if secret is None:
        logger.error("two-step secret of web user %s cannot be read (SECRET_KEY changed?)", user_id)
        return None
    step = totp.match_step(secret, code)
    if step is not None and await accept_totp_step(user_id, step):
        return "totp"
    return None
