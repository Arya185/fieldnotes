"""Workspace identity and registry management."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from backend.config import WORKSPACE_REGISTRY_DB_PATH
from backend.auth.security import auth_config
from backend.indexer.registry_database import RegistryDatabase
from backend.indexer.workspace import get_workspace_paths, initialize_workspace
from backend.indexer.workspace_repository import WorkspaceRepository

logger = logging.getLogger("fieldnotes.registry")

DEFAULT_WORKSPACE_STATUS = "idle"
DEFAULT_USER_ID = "local_admin"
DEFAULT_USER_EMAIL = "local@fieldnotes.local"
DEFAULT_USER_PROVIDER = "local"
DEFAULT_USER_PROVIDER_ID = "local_admin"


@dataclass(frozen=True)
class WorkspaceRecord:
    workspace_id: str
    root: Path
    db_path: Path
    artifacts_dir: Path
    metadata_path: Path


class WorkspaceManager:
    """Manage stable workspace IDs and persisted registry metadata."""

    def __init__(self, registry_path: Path = WORKSPACE_REGISTRY_DB_PATH) -> None:
        self.registry_dir = registry_path.parent
        self.legacy_registry_path = self.registry_dir / "workspaces.json"
        if registry_path.name == self.legacy_registry_path.name:
            self.registry_path = self.registry_dir / WORKSPACE_REGISTRY_DB_PATH.name
        else:
            self.registry_path = registry_path
        self._cache: dict[str, WorkspaceRecord] = {}
        self._last_recovery_warning: str | None = None
        self._database = RegistryDatabase(self.registry_path)
        self._repository = WorkspaceRepository(self._database)
        self._ensure_registry()

    def register_workspace(self, workspace_root: Path) -> WorkspaceRecord:
        return self.register(workspace_root)

    def get_workspace(self, workspace_id: str) -> WorkspaceRecord | None:
        return self.get(workspace_id)

    def list_workspaces(self) -> list[WorkspaceRecord]:
        rows = self._repository.list_workspaces()
        return [self._workspace_record_from_row(row) for row in rows]

    def update_workspace(
        self,
        workspace_id: str,
        *,
        root: Path | None = None,
        title: str | None = None,
        status: str | None = None,
        metadata_json: str | None = None,
    ) -> None:
        fields: dict[str, object] = {}
        if root is not None:
            fields["root"] = str(root.expanduser().resolve())
        if title is not None:
            fields["title"] = title
        if status is not None:
            fields["status"] = status
        if metadata_json is not None:
            fields["metadata_json"] = metadata_json
        self._repository.update_workspace(workspace_id, **fields)
        self._cache.pop(workspace_id, None)

    def delete_workspace(self, workspace_id: str) -> None:
        self._repository.delete_workspace(workspace_id)
        self._cache.pop(workspace_id, None)

    def add_member(self, workspace_id: str, user_id: str, role: str) -> None:
        self._repository.add_member(workspace_id, user_id, role)

    def remove_member(self, workspace_id: str, user_id: str) -> None:
        self._repository.remove_member(workspace_id, user_id)

    def register(self, workspace_root: Path, creator: AuthenticatedUser | None = None) -> WorkspaceRecord:
        auth_config.refresh()
        workspace_root = workspace_root.expanduser().resolve()
        paths = initialize_workspace(workspace_root)
        metadata_path = paths.fieldnotes_dir / "workspace.json"

        record = self._repository.get_workspace_by_root(workspace_root)
        if record is not None:
            if auth_config.enabled and creator is not None:
                role = self._repository.get_member_role(record.workspace_id, creator["user_id"])
                if role is None:
                    raise PermissionError("User is not a member of this workspace")
            workspace_id = record.workspace_id
            workspace_record = WorkspaceRecord(
                workspace_id=workspace_id,
                root=workspace_root,
                db_path=paths.db_path,
                artifacts_dir=paths.artifacts_dir,
                metadata_path=metadata_path,
            )
            self._cache[workspace_id] = workspace_record
            self._write_workspace_metadata(workspace_record)
            return workspace_record

        workspace_id = self._repository.insert_workspace(workspace_root, workspace_root.name, DEFAULT_WORKSPACE_STATUS)
        if auth_config.enabled and creator is not None:
            self._repository.insert_user(
                creator["user_id"],
                creator["email"],
                creator["name"],
                creator["provider"],
                creator["provider_id"],
            )
            self._repository.add_member(workspace_id, creator["user_id"], "owner")
        else:
            self._ensure_local_admin()

        workspace_record = WorkspaceRecord(
            workspace_id=workspace_id,
            root=workspace_root,
            db_path=paths.db_path,
            artifacts_dir=paths.artifacts_dir,
            metadata_path=metadata_path,
        )
        self._cache[workspace_id] = workspace_record
        self._write_workspace_metadata(workspace_record)
        return workspace_record

    def get(self, workspace_id: str) -> WorkspaceRecord | None:
        cached = self._cache.get(workspace_id)
        if cached is not None:
            return cached

        record = self._repository.get_workspace(workspace_id)
        if record is None:
            return None

        workspace_root = Path(record.root)
        paths = get_workspace_paths(workspace_root)
        workspace_record = WorkspaceRecord(
            workspace_id=record.workspace_id,
            root=workspace_root,
            db_path=paths.db_path,
            artifacts_dir=paths.artifacts_dir,
            metadata_path=paths.fieldnotes_dir / "workspace.json",
        )
        self._cache[workspace_id] = workspace_record
        return workspace_record

    def last_recovery_warning(self) -> str | None:
        return self._database.last_recovery_warning

    def _ensure_registry(self) -> None:
        auth_config.refresh()
        self.registry_dir.mkdir(parents=True, exist_ok=True)
        if self.legacy_registry_path.exists():
            self._migrate_legacy_json_registry()
        if not auth_config.enabled:
            self._ensure_local_admin()

    def _migrate_legacy_json_registry(self) -> None:
        try:
            raw = self.legacy_registry_path.read_text(encoding="utf-8")
            payload = json.loads(raw)
        except Exception as exc:
            logger.warning("Could not migrate legacy workspace registry: %s", exc)
            return

        if not isinstance(payload, dict):
            return

        for workspace_id, root_str in payload.items():
            if not isinstance(workspace_id, str) or not isinstance(root_str, str):
                continue
            root = Path(root_str).expanduser().resolve()
            if self._repository.get_workspace_by_root(root) is not None:
                continue
            self._repository.insert_workspace(root, root.name, DEFAULT_WORKSPACE_STATUS, workspace_id=workspace_id)

        try:
            self.legacy_registry_path.unlink()
        except OSError:
            pass

    def _quarantine_registry_db(self) -> None:
        if not self.registry_path.exists():
            return
        timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H%M%SZ")
        quarantine_path = self.registry_path.with_name(f"{self.registry_path.name}.corrupt-{timestamp}")
        suffix = 1
        while quarantine_path.exists():
            quarantine_path = self.registry_path.with_name(f"{self.registry_path.name}.corrupt-{timestamp}-{suffix}")
            suffix += 1
        try:
            self.registry_path.replace(quarantine_path)
        except OSError:
            logger.warning("workspace registry quarantine skipped: permission denied for %s", self.registry_path)

    def _ensure_local_admin(self) -> None:
        self._repository.insert_user(
            DEFAULT_USER_ID,
            DEFAULT_USER_EMAIL,
            "Local Admin",
            DEFAULT_USER_PROVIDER,
            DEFAULT_USER_PROVIDER_ID,
        )
        with self._database.connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO workspace_members (workspace_id, user_id, role, joined_at) SELECT workspace_id, ?, 'owner', ? FROM workspaces",
                (DEFAULT_USER_ID, datetime.now(UTC).isoformat()),
            )
            connection.commit()

    def _get_workspace_id_by_root(self, workspace_root: Path) -> str | None:
        record = self._repository.get_workspace_by_root(workspace_root)
        return record.workspace_id if record is not None else None

    def _workspace_record_from_row(self, row: sqlite3.Row) -> WorkspaceRecord:
        workspace_root = Path(row["root"])
        paths = get_workspace_paths(workspace_root)
        return WorkspaceRecord(
            workspace_id=row["workspace_id"],
            root=workspace_root,
            db_path=paths.db_path,
            artifacts_dir=paths.artifacts_dir,
            metadata_path=paths.fieldnotes_dir / "workspace.json",
        )

    def _utc_now_iso(self) -> str:
        return datetime.now(UTC).isoformat()

    def _write_workspace_metadata(self, record: WorkspaceRecord) -> None:
        record.metadata_path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {
                "workspace_id": record.workspace_id,
                "root": str(record.root),
                "db_path": str(record.db_path),
                "artifacts_dir": str(record.artifacts_dir),
            },
            indent=2,
            sort_keys=True,
        )
        record.metadata_path.write_text(payload, encoding="utf-8")


workspace_manager = WorkspaceManager()
