"""Persistence for the optional Google Drive import integration's OAuth credential.

The access/refresh token here is used only to list and download files at
import time (backend/services/google_drive.py). Once a file is imported it
is written into the local workspace folder and behaves exactly like any
other local file — the token is never used again for that file.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime


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
        (user_id, access_token, refresh_token, expires_at, scope, datetime.now(UTC).isoformat()),
    )
    connection.commit()


def load_drive_credentials(connection: sqlite3.Connection, user_id: str) -> dict | None:
    row = connection.execute(
        "SELECT access_token, refresh_token, expires_at, scope FROM google_drive_credentials WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    return None if row is None else dict(row)
