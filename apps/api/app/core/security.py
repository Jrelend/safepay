"""Password hashing, opaque tokens and constant-time comparison."""

import hashlib
import hmac
import secrets
from functools import lru_cache
from typing import Final

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

MIN_PASSWORD_LENGTH: Final = 10
MAX_PASSWORD_LENGTH: Final = 128
# Rejected regardless of length; extend with a breached-password list later.
_COMMON_PASSWORDS: Final = frozenset(
    {"password123", "1234567890", "qwertyuiop", "0123456789", "password1!", "safepay123"}
)


@lru_cache
def _hasher() -> PasswordHasher:
    # argon2-cffi defaults are Argon2id (RFC 9106 low-memory profile).
    return PasswordHasher()


@lru_cache
def _dummy_hash() -> str:
    return _hasher().hash(secrets.token_urlsafe(16))


def hash_password(password: str) -> str:
    return _hasher().hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    """Constant-ish time: an unknown user still pays for one Argon2 verification."""
    target = password_hash or _dummy_hash()
    ok: bool
    try:
        ok = _hasher().verify(target, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        ok = False
    return ok and password_hash is not None


def needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher().check_needs_rehash(password_hash)
    except InvalidHashError:
        return False


class WeakPasswordError(ValueError):
    pass


def check_password_policy(password: str, *, email: str) -> None:
    if not MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH:
        raise WeakPasswordError(
            f"password must be {MIN_PASSWORD_LENGTH}-{MAX_PASSWORD_LENGTH} characters"
        )
    lowered = password.lower()
    if lowered in _COMMON_PASSWORDS or lowered == email.lower() or len(set(password)) < 4:
        raise WeakPasswordError("password is too easy to guess")


def new_token() -> str:
    """256-bit URL-safe random token."""
    return secrets.token_urlsafe(32)


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())
