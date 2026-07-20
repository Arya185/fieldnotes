"""Workspace identity and registry management."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import uuid4

from backend.config import WORKSPACE_REGISTRY_DIR, WORKSPACE_REGISTRY_PATH
from backend.indexer.workspace import get_workspace_paths, initialize_workspace

logger = logging.getLogger("fieldnotes.registry")


@dataclass(frozen=True)
class WorkspaceRecord:
    workspace_id: str
    root: Path
    db_path: Path
    artifacts_dir: Path
    metadata_path: Path


class WorkspaceManager:
    """Manage stable workspace IDs and persisted registry metadata."""

    def __init__(self, registry_path: Path = WORKSPACE_REGISTRY_PATH) -> None:
        self.registry_path = registry_path
        self.backup_path = registry_path.with_name("workspaces.backup.json")
        self._cache: dict[str, WorkspaceRecord] = {}
        self._last_recovery_warning: str | None = None

    def register(self, workspace_root: Path) -> WorkspaceRecord:
        workspace_root = workspace_root.expanduser().resolve()
        paths = initialize_workspace(workspace_root)
        metadata_path = paths.fieldnotes_dir / "workspace.json"
        registry = self._load_registry()

        for workspace_id, root_str in registry.items():
            if Path(root_str) == workspace_root:
                record = WorkspaceRecord(
                    workspace_id=workspace_id,
                    root=workspace_root,
                    db_path=paths.db_path,
                    artifacts_dir=paths.artifacts_dir,
                    metadata_path=metadata_path,
                )
                self._cache[workspace_id] = record
                self._write_workspace_metadata(record)
                return record

        workspace_id = str(uuid4())
        registry[workspace_id] = str(workspace_root)
        self._save_registry(registry)
        record = WorkspaceRecord(
            workspace_id=workspace_id,
            root=workspace_root,
            db_path=paths.db_path,
            artifacts_dir=paths.artifacts_dir,
            metadata_path=metadata_path,
        )
        self._cache[workspace_id] = record
        self._write_workspace_metadata(record)
        return record

    def get(self, workspace_id: str) -> WorkspaceRecord | None:
        cached = self._cache.get(workspace_id)
        if cached is not None:
            return cached

        registry = self._load_registry()
        root_str = registry.get(workspace_id)
        if root_str is None:
            return None

        workspace_root = Path(root_str)
        paths = get_workspace_paths(workspace_root)
        record = WorkspaceRecord(
            workspace_id=workspace_id,
            root=workspace_root,
            db_path=paths.db_path,
            artifacts_dir=paths.artifacts_dir,
            metadata_path=paths.fieldnotes_dir / "workspace.json",
        )
        self._cache[workspace_id] = record
        return record

    def last_recovery_warning(self) -> str | None:
        return self._last_recovery_warning

    def _load_registry(self) -> dict[str, str]:
        self._last_recovery_warning = None
        if not self.registry_path.exists():
            return {}
        try:
            raw = self.registry_path.read_text(encoding="utf-8")
        except PermissionError as exc:
            return self._recover_registry("Registry file could not be read and was recreated.", exc)
        except OSError as exc:
            return self._recover_registry("Registry file could not be read and was recreated.", exc)

        if not raw.strip():
            return self._recover_registry("Registry file was empty and was recreated.")

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            return self._recover_registry("Registry file was corrupted and was recreated.", exc)

        if not isinstance(payload, dict) or not all(
            isinstance(key, str) and isinstance(value, str) for key, value in payload.items()
        ):
            return self._recover_registry("Registry file contents were invalid and were recreated.")
        return payload

    def _save_registry(self, registry: dict[str, str]) -> None:
        WORKSPACE_REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
        self._write_backup_if_possible()
        try:
            self._atomic_write_json(self.registry_path, registry)
        except PermissionError as exc:
            logger.warning("workspace registry save failed: %s", exc)
            self._last_recovery_warning = "Workspace registry could not be updated on disk."
        except OSError as exc:
            logger.warning("workspace registry save failed: %s", exc)
            self._last_recovery_warning = "Workspace registry could not be updated on disk."

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
        self._atomic_write_text(record.metadata_path, payload)

    def _recover_registry(self, message: str, exc: Exception | None = None) -> dict[str, str]:
        self._last_recovery_warning = message
        if exc is None:
            logger.warning("workspace registry recovery: %s", message)
        else:
            logger.warning("workspace registry recovery: %s", message, exc_info=(type(exc), exc, exc.__traceback__))
        self._quarantine_registry_if_possible()
        self._initialize_empty_registry_if_possible()
        return {}

    def _quarantine_registry_if_possible(self) -> None:
        if not self.registry_path.exists():
            return
        timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H%M%SZ")
        quarantine_path = self.registry_path.with_name(f"workspaces.corrupt-{timestamp}.json")
        suffix = 1
        while quarantine_path.exists():
            quarantine_path = self.registry_path.with_name(f"workspaces.corrupt-{timestamp}-{suffix}.json")
            suffix += 1
        try:
            self.registry_path.replace(quarantine_path)
        except PermissionError:
            logger.warning("workspace registry quarantine skipped: permission denied for %s", self.registry_path)
        except OSError as exc:
            logger.warning("workspace registry quarantine failed: %s", exc)

    def _initialize_empty_registry_if_possible(self) -> None:
        try:
            self._atomic_write_json(self.registry_path, {})
        except PermissionError:
            logger.warning("workspace registry recreation skipped: permission denied for %s", self.registry_path)
        except OSError as exc:
            logger.warning("workspace registry recreation failed: %s", exc)

    def _write_backup_if_possible(self) -> None:
        if not self.registry_path.exists():
            return
        try:
            payload = self._load_registry_text_for_backup()
            if payload is None:
                return
            self._atomic_write_text(self.backup_path, payload)
        except PermissionError:
            logger.warning("workspace registry backup skipped: permission denied for %s", self.backup_path)
        except OSError as exc:
            logger.warning("workspace registry backup failed: %s", exc)

    def _load_registry_text_for_backup(self) -> str | None:
        try:
            raw = self.registry_path.read_text(encoding="utf-8")
        except OSError:
            return None
        if not raw.strip():
            return None
        try:
            json.loads(raw)
        except json.JSONDecodeError:
            return None
        return raw

    def _atomic_write_json(self, path: Path, payload: dict[str, str]) -> None:
        self._atomic_write_text(path, json.dumps(payload, indent=2, sort_keys=True))

    def _atomic_write_text(self, path: Path, payload: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            delete=False,
        ) as temp_file:
            temp_file.write(payload)
            temp_file.flush()
            os.fsync(temp_file.fileno())
            temp_path = Path(temp_file.name)
        temp_path.replace(path)
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)


workspace_manager = WorkspaceManager()
