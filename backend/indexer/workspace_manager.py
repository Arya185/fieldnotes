"""Workspace identity and registry management."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import uuid4

from backend.config import WORKSPACE_REGISTRY_DIR, WORKSPACE_REGISTRY_PATH
from backend.indexer.workspace import get_workspace_paths, initialize_workspace


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
        self._cache: dict[str, WorkspaceRecord] = {}

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

    def _load_registry(self) -> dict[str, str]:
        if not self.registry_path.exists():
            return {}
        return json.loads(self.registry_path.read_text(encoding="utf-8"))

    def _save_registry(self, registry: dict[str, str]) -> None:
        WORKSPACE_REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=WORKSPACE_REGISTRY_DIR,
            delete=False,
        ) as temp_file:
            temp_file.write(json.dumps(registry, indent=2, sort_keys=True))
            temp_path = Path(temp_file.name)
        temp_path.replace(self.registry_path)

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
        with NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=record.metadata_path.parent,
            delete=False,
        ) as temp_file:
            temp_file.write(payload)
            temp_path = Path(temp_file.name)
        temp_path.replace(record.metadata_path)


workspace_manager = WorkspaceManager()
