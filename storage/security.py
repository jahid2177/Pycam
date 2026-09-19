"""Local PIN security helpers.

PINs are never stored as plaintext. A random salt + PBKDF2-HMAC-SHA256
hash are kept in AppPreferences. This is intended for local app/privacy
locking, not as a substitute for encrypted-at-rest document storage.
"""

import hashlib
import hmac
import os

_ITERATIONS = 180_000


def _hash_pin(pin: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac(
        "sha256", pin.encode("utf-8"), salt, _ITERATIONS, dklen=32
    )


def is_valid_pin_format(pin: str) -> bool:
    return isinstance(pin, str) and pin.isdigit() and 4 <= len(pin) <= 8


def has_pin(prefs) -> bool:
    return bool(prefs.get("pin_salt") and prefs.get("pin_hash"))


def set_pin(prefs, pin: str) -> None:
    if not is_valid_pin_format(pin):
        raise ValueError("PIN must contain 4 to 8 digits.")
    salt = os.urandom(16)
    digest = _hash_pin(pin, salt)
    prefs.set("pin_salt", salt.hex())
    prefs.set("pin_hash", digest.hex())


def verify_pin(prefs, pin: str) -> bool:
    try:
        salt_hex = prefs.get("pin_salt") or ""
        digest_hex = prefs.get("pin_hash") or ""
        if not salt_hex or not digest_hex:
            return False
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
        actual = _hash_pin(str(pin), salt)
        return hmac.compare_digest(expected, actual)
    except Exception:
        return False


def clear_pin(prefs) -> None:
    prefs.set("app_lock_enabled", False)
    prefs.set("biometric_unlock", False)
    prefs.set("pin_salt", "")
    prefs.set("pin_hash", "")
