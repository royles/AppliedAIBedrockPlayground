"""SQLite persistence for LLM provider configuration (secrets encrypted)."""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from app.config import get_settings
from app.crypto_util import decrypt_secret, encrypt_secret

logger = logging.getLogger(__name__)

Provider = Literal["bedrock", "local"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS llm_config (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    provider TEXT NOT NULL,
    model_id TEXT NOT NULL,
    aws_region TEXT NOT NULL,
    local_endpoint_url TEXT NOT NULL DEFAULT '',
    local_model_id TEXT NOT NULL DEFAULT '',
    local_api_token_encrypted BLOB,
    updated_at TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class PersistedConfig:
    provider: Provider
    model_id: str
    aws_region: str
    local_endpoint_url: str
    local_model_id: str
    local_api_token: str


def _db_path() -> Path:
    settings = get_settings()
    if settings.config_db_path:
        return Path(settings.config_db_path)
    return Path(__file__).resolve().parent.parent / "data" / "playground.db"


def _connect() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.executescript(_SCHEMA)
    return conn


def load_persisted_config() -> PersistedConfig | None:
    try:
        with _connect() as conn:
            row = conn.execute(
                """
                SELECT provider, model_id, aws_region, local_endpoint_url,
                       local_model_id, local_api_token_encrypted
                FROM llm_config WHERE id = 1
                """
            ).fetchone()
    except sqlite3.Error as exc:
        logger.warning("Could not read config database: %s", exc)
        return None

    if not row:
        return None

    provider, model_id, aws_region, local_endpoint_url, local_model_id, token_blob = row
    if provider not in ("bedrock", "local"):
        logger.warning("Ignoring invalid persisted provider=%r", provider)
        return None

    try:
        token = decrypt_secret(token_blob)
    except ValueError:
        token = ""

    logger.info("Loaded LLM configuration from %s", _db_path())
    return PersistedConfig(
        provider=provider,
        model_id=model_id or "",
        aws_region=aws_region or "",
        local_endpoint_url=local_endpoint_url or "",
        local_model_id=local_model_id or "",
        local_api_token=token,
    )


def save_persisted_config(
    *,
    provider: Provider,
    model_id: str,
    aws_region: str,
    local_endpoint_url: str,
    local_model_id: str,
    local_api_token: str,
) -> None:
    token_blob = encrypt_secret(local_api_token)
    updated_at = datetime.now(timezone.utc).isoformat()
    try:
        with _connect() as conn:
            conn.execute(
                """
                INSERT INTO llm_config (
                    id, provider, model_id, aws_region,
                    local_endpoint_url, local_model_id,
                    local_api_token_encrypted, updated_at
                ) VALUES (1, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    provider = excluded.provider,
                    model_id = excluded.model_id,
                    aws_region = excluded.aws_region,
                    local_endpoint_url = excluded.local_endpoint_url,
                    local_model_id = excluded.local_model_id,
                    local_api_token_encrypted = excluded.local_api_token_encrypted,
                    updated_at = excluded.updated_at
                """,
                (
                    provider,
                    model_id,
                    aws_region,
                    local_endpoint_url,
                    local_model_id,
                    token_blob,
                    updated_at,
                ),
            )
            conn.commit()
    except sqlite3.Error as exc:
        logger.error("Failed to save LLM configuration: %s", exc)
        raise
