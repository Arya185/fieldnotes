"""Workspace registry persistence operations."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from backend.indexer.registry_database import RegistryDatabase


@dataclass(frozen=True)
class WorkspaceRecordRow:
    workspace_id: str
    root: str
    title: str
    status: str
    created_at: str
    updated_at: str
    metadata_json: str | None


class WorkspaceRepository:
    """CRUD operations for workspace registry data."""

    def __init__(self, database: RegistryDatabase) -> None:
        self.database = database

    def list_workspaces(self) -> list[WorkspaceRecordRow]:
        with self.database.connect() as connection:
            rows = connection.execute("SELECT * FROM workspaces ORDER BY created_at").fetchall()
        return [WorkspaceRecordRow(**dict(row)) for row in rows]

    def get_workspace(self, workspace_id: str) -> WorkspaceRecordRow | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM workspaces WHERE workspace_id = ?",
                (workspace_id,),
            ).fetchone()
        return WorkspaceRecordRow(**dict(row)) if row is not None else None

    def get_workspace_by_root(self, root: Path) -> WorkspaceRecordRow | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM workspaces WHERE root = ?",
                (str(root),),
            ).fetchone()
        return WorkspaceRecordRow(**dict(row)) if row is not None else None

    def insert_workspace(self, root: Path, title: str, status: str, workspace_id: str | None = None) -> str:
        workspace_id = workspace_id or str(uuid4())
        now = datetime.now(UTC).isoformat()
        with self.database.connect() as connection:
            connection.execute(
                "INSERT INTO workspaces (workspace_id, root, title, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (workspace_id, str(root), title, status, now, now),
            )
            connection.commit()
        return workspace_id

    def update_workspace(self, workspace_id: str, **fields: object) -> None:
        if not fields:
            return
        clauses = []
        parameters: list[object] = []
        for key, value in fields.items():
            clauses.append(f"{key} = ?")
            parameters.append(value)
        parameters.append(datetime.now(UTC).isoformat())
        parameters.append(workspace_id)
        with self.database.connect() as connection:
            connection.execute(
                f"UPDATE workspaces SET {', '.join(clauses)}, updated_at = ? WHERE workspace_id = ?",
                parameters,
            )
            connection.commit()

    def delete_workspace(self, workspace_id: str) -> None:
        with self.database.connect() as connection:
            connection.execute("DELETE FROM workspaces WHERE workspace_id = ?", (workspace_id,))
            connection.commit()

    def get_member_role(self, workspace_id: str, user_id: str) -> str | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT role FROM workspace_members WHERE workspace_id = ? AND user_id = ?",
                (workspace_id, user_id),
            ).fetchone()
        return str(row["role"]) if row is not None else None

    def insert_user(self, user_id: str, email: str, name: str, provider: str, provider_id: str) -> None:
        now = datetime.now(UTC).isoformat()
        with self.database.connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO users (user_id, email, name, avatar_url, provider, provider_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (user_id, email, name, "", provider, provider_id, now, now),
            )
            connection.commit()

    def add_member(self, workspace_id: str, user_id: str, role: str) -> None:
        with self.database.connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO workspace_members (workspace_id, user_id, role, joined_at) VALUES (?, ?, ?, ?)",
                (workspace_id, user_id, role, datetime.now(UTC).isoformat()),
            )
            connection.commit()

    def remove_member(self, workspace_id: str, user_id: str) -> None:
        with self.database.connect() as connection:
            connection.execute(
                "DELETE FROM workspace_members WHERE workspace_id = ? AND user_id = ?",
                (workspace_id, user_id),
            )
            connection.commit()
