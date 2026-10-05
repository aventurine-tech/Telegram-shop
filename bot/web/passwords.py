"""Password hashing for web-panel accounts (standard library only).

Format: ``scrypt$<n>$<r>$<p>$<salt hex>$<hash hex>``. Verification is constant-time, and an
unknown username is checked against a dummy hash so response time doesn't reveal which
usernames exist.
"""
import hashlib
import hmac
import secrets

_N, _R, _P = 2 ** 14, 8, 1
_KEYLEN = 32
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128


def _scrypt(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p,
                          dklen=_KEYLEN, maxmem=64 * 1024 * 1024)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = _scrypt(password, salt, _N, _R, _P)
    return f"scrypt${_N}${_R}${_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    """True if ``password`` matches ``stored``. A missing/garbled hash never verifies."""
    try:
        algo, n, r, p, salt_hex, hash_hex = (stored or "").split("$")
        if algo != "scrypt":
            return False
        expected = bytes.fromhex(hash_hex)
        actual = _scrypt(password, bytes.fromhex(salt_hex), int(n), int(r), int(p))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


# Burned on a username miss so a wrong user costs the same as a wrong password.
DUMMY_HASH = hash_password(secrets.token_hex(16))


def check_password_strength(password: str) -> str | None:
    """None if acceptable, else a stable error code."""
    if len(password) < MIN_PASSWORD_LENGTH:
        return "password_too_short"
    if len(password) > MAX_PASSWORD_LENGTH:
        return "password_too_long"
    return None
