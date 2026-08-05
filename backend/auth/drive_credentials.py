"""Persistence for optional Google Drive import credentials.

Encrypted at rest. Plaintext fallback forbidden.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import UTC, datetime

from cryptography.fernet import Fernet, InvalidToken

from backend.auth.security import is_non_local_environment

TOKEN_ENCRYPTION_KEY_ENV = "FIELDNOTES_TOKEN_ENCRYPTION_KEY"


def validate_token_encryption_configuration(*, require_for_startup: bool) -> str:
    if os.environ.get(TOKEN_ENCRYPTION_KEY_ENV):
        return "configured"
    if require_for_startup and is_non_local_environment():
        raise RuntimeError(
            f"{TOKEN_ENCRYPTION_KEY_ENV} must be set in non-local environments."
        )
    return "optional_unset"


def _get_cipher() -> Fernet:
    key = os.environ.get(TOKEN_ENCRYPTION_KEY_ENV)
    if not key:
        raise RuntimeError(
            f"{TOKEN_ENCRYPTION_KEY_ENV} is required before storing or reading Google Drive credentials."
        )
    return Fernet(key.encode("utf-8"))


def _encrypt_token(value: str | None) -> str | None:
    if value is None:
        return None
    return _get_cipher().encrypt(value.encode("utf-8")).decode("utf-8")


def _decrypt_token(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        return _get_cipher().decrypt(value.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise RuntimeError(
            "Stored Google Drive credentials could not be decrypted. Reconnect Google Drive."
        ) from exc


def save_drive_credentials(
    connection: sqlite3.Connection,
    user_id: str,
    *,
    access_token: str,
    refresh_token: str | None,
    expires_at: str | None,
    scope: str | None,
) -> None:
    connection.execute(
        """
        INSERT INTO google_drive_credentials (
          user_id, access_token, refresh_token, expires_at, scope, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
          access_token = excluded.access_token,
          refresh_token = COALESCE(excluded.refresh_token, google_drive_credentials.refresh_token),
          expires_at = excluded.expires_at,
          scope = excluded.scope,
          updated_at = excluded.updated_at
        """,
        (
            user_id,
            _encrypt_token(access_token),
            _encrypt_token(refresh_token),
            expires_at,
            scope,
            datetime.now(UTC).isoformat(),
        ),
    )
    connection.commit()


def load_drive_credentials(connection: sqlite3.Connection, user_id: str) -> dict | None:
    row = connection.execute(
        "SELECT access_token, refresh_token, expires_at, scope FROM google_drive_credentials WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "access_token": _decrypt_token(row["access_token"]),
        "refresh_token": _decrypt_token(row["refresh_token"]),
        "expires_at": row["expires_at"],
        "scope": row["scope"],
    }
