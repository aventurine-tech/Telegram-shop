"""Two-step sign-in for panel accounts: time-based one-time codes (RFC 6238) and one-time backup codes.

Standard 6-digit / 30-second codes, so any authenticator app works. No extra dependency. The shared secret is stored
encrypted with a key derived from ``SECRET_KEY``; backup codes are stored only as keyed hashes.
"""
import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

from cryptography.fernet import Fernet, InvalidToken

from bot.misc import EnvKeys

PERIOD = 30
DIGITS = 6
WINDOW = 1                  # a code from the previous / next 30 seconds is accepted (clock drift)
BACKUP_COUNT = 8
_BACKUP_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"       # no look-alikes (0/o, 1/l/i)


def new_secret() -> str:
    """A fresh 160-bit shared secret, base32 (what authenticator apps expect)."""
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _key(secret: str) -> bytes:
    return base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)


def code_at(secret: str, step: int) -> str:
    digest = hmac.new(_key(secret), struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    number = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % 10 ** DIGITS
    return str(number).zfill(DIGITS)


def current_step(now: float | None = None) -> int:
    return int((time.time() if now is None else now) // PERIOD)


def match_step(secret: str, code: str, now: float | None = None) -> int | None:
    """The 30-second step the typed code belongs to (within the drift window), else None."""
    code = "".join(ch for ch in (code or "") if ch.isdigit())
    if len(code) != DIGITS:
        return None
    step = current_step(now)
    for candidate in range(step - WINDOW, step + WINDOW + 1):
        if hmac.compare_digest(code_at(secret, candidate), code):
            return candidate
    return None


def provisioning_uri(secret: str, username: str, issuer: str) -> str:
    label = quote(f"{issuer}:{username}", safe="")
    return f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer, safe='')}&digits={DIGITS}&period={PERIOD}"


def qr_svg(uri: str) -> str:
    """The setup link as an inline SVG QR code ('' if the segno package is missing: the typed key still works)."""
    try:
        import segno
    except ImportError:
        return ""
    return segno.make(uri, error="m", micro=False).svg_inline(scale=5, border=2, dark="#000", light="#fff")


def group(secret: str) -> str:
    """The secret in groups of four, easier to type by hand."""
    return " ".join(secret[i:i + 4] for i in range(0, len(secret), 4))


# --- storing the secret -------------------------------------------------------------------------------------------

def _fernet() -> Fernet:
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(b"totp|" + EnvKeys.SECRET_KEY.encode()).digest()))


def seal(secret: str) -> str:
    return _fernet().encrypt(secret.encode()).decode()


def unseal(token: str | None) -> str | None:
    """The secret, or None when it is missing or was sealed with another SECRET_KEY."""
    if not token:
        return None
    try:
        return _fernet().decrypt(token.encode()).decode()
    except (InvalidToken, ValueError):
        return None


# --- backup codes -------------------------------------------------------------------------------------------------

def new_backup_codes(count: int = BACKUP_COUNT) -> list[str]:
    """Codes like ``k7m2-q9xd``: shown once, each works once."""
    return ["".join(secrets.choice(_BACKUP_ALPHABET) for _ in range(8)) for _ in range(count)]


def show_backup(code: str) -> str:
    return f"{code[:4]}-{code[4:]}"


def _normal_backup(code: str) -> str:
    return "".join(ch for ch in (code or "").lower() if ch.isalnum())


def backup_hash(code: str) -> str:
    return hmac.new(b"backup|" + EnvKeys.SECRET_KEY.encode(), _normal_backup(code).encode(), hashlib.sha256).hexdigest()


def looks_like_backup(code: str) -> bool:
    return len(_normal_backup(code)) == 8
