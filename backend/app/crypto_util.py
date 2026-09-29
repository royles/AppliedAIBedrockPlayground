"""Encrypt sensitive config values at rest (local LLM API tokens)."""

from __future__ import annotations

import logging
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings

logger = logging.getLogger(__name__)


def _key_file_path() -> Path:
    settings = get_settings()
    if settings.config_encryption_key_file:
        return Path(settings.config_encryption_key_file)
    return Path(__file__).resolve().parent.parent / "data" / ".fernet_key"


def _load_or_create_key_file(path: Path) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        key = path.read_bytes().strip()
        if key:
            return key
    key = Fernet.generate_key()
    path.write_bytes(key)
    try:
        path.chmod(0o600)
    except OSError:
        pass
    logger.info("Generated Fernet key at %s (set CONFIG_ENCRYPTION_KEY for multi-instance deploys)", path)
    return key


def get_fernet() -> Fernet:
    settings = get_settings()
    raw = (settings.config_encryption_key or "").strip()
    if raw:
        return Fernet(raw.encode("utf-8"))
    return Fernet(_load_or_create_key_file(_key_file_path()))


def encrypt_secret(plaintext: str) -> bytes | None:
    if not plaintext:
        return None
    return get_fernet().encrypt(plaintext.encode("utf-8"))


def decrypt_secret(ciphertext: bytes | None) -> str:
    if not ciphertext:
        return ""
    try:
        return get_fernet().decrypt(ciphertext).decode("utf-8")
    except InvalidToken as exc:
        logger.error("Failed to decrypt stored local API token (wrong CONFIG_ENCRYPTION_KEY?)")
        raise ValueError("Stored local API token cannot be decrypted.") from exc
