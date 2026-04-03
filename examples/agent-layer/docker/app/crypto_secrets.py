"""Fernet encrypt/decrypt for user secrets at rest (key from AGENT_SECRETS_MASTER_KEY)."""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from . import config

_fernet: Fernet | None = None


def _fernet_instance() -> Fernet:
    global _fernet
    if _fernet is not None:
        return _fernet
    raw = config.SECRETS_MASTER_KEY
    if not raw:
        raise RuntimeError("AGENT_SECRETS_MASTER_KEY is not set")
    key = raw.encode("utf-8") if isinstance(raw, str) else raw
    _fernet = Fernet(key)
    return _fernet


def encrypt_secret(plaintext: str) -> bytes:
    return _fernet_instance().encrypt(plaintext.encode("utf-8"))


def decrypt_secret(ciphertext: bytes) -> str:
    try:
        return _fernet_instance().decrypt(ciphertext).decode("utf-8")
    except InvalidToken as e:
        raise ValueError("decryption failed (wrong key or corrupt data)") from e


def secrets_available() -> bool:
    return bool(config.SECRETS_MASTER_KEY)
