"""Workspace initialization helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from backend.db import connect_sqlite, initialize_schema


@dataclass(frozen=True)
class WorkspacePaths:
    root: Path
    fieldnotes_dir: Path
    db_path: Path
    artifacts_dir: Path


def get_workspace_paths(workspace_root: Path) -> WorkspacePaths:
    """Build canonical workspace paths for Fieldnotes local state."""

    fieldnotes_dir = workspace_root / ".fieldnotes"
    return WorkspacePaths(
        root=workspace_root,
        fieldnotes_dir=fieldnotes_dir,
        db_path=fieldnotes_dir / "fieldnotes.db",
        artifacts_dir=fieldnotes_dir / "artifacts",
    )


def initialize_workspace(workspace_root: Path) -> WorkspacePaths:
    """Ensure local workspace directories and SQLite schema exist."""

    paths = get_workspace_paths(workspace_root)
    paths.fieldnotes_dir.mkdir(parents=True, exist_ok=True)
    paths.artifacts_dir.mkdir(parents=True, exist_ok=True)

    connection = connect_sqlite(paths.db_path)
    try:
        initialize_schema(connection)
    finally:
        connection.close()

    return paths
