"""Recursive discovery for supported workspace files."""

from __future__ import annotations

import os
from pathlib import Path

from backend.indexer.parsers import DiscoveredFile, SUPPORTED_FILE_TYPES


SUPPORTED_SUFFIXES: dict[str, str] = {
    ".pdf": "pdf",
    ".pptx": "pptx",
    ".docx": "docx",
    ".md": "md",
    ".txt": "txt",
    ".csv": "csv",
}
IGNORED_DIR_NAMES = {".fieldnotes", ".git", "__pycache__", "node_modules"}


def detect_kind(path: Path) -> str | None:
    """Return supported kind for file path, or None if unsupported."""

    return SUPPORTED_SUFFIXES.get(path.suffix.lower())


def discover_files(workspace_root: Path) -> list[DiscoveredFile]:
    """Recursively discover supported files under workspace root."""

    discovered: list[DiscoveredFile] = []
    for current_root, dir_names, file_names in os.walk(workspace_root):
        dir_names[:] = sorted(name for name in dir_names if name not in IGNORED_DIR_NAMES)
        current_path = Path(current_root)
        for file_name in sorted(file_names):
            path = current_path / file_name
            kind = detect_kind(path)
            if kind is None:
                continue
            relative_path = str(path.relative_to(workspace_root))
            try:
                size_bytes = path.stat().st_size
            except OSError:
                size_bytes = 0
            discovered.append(
                DiscoveredFile(
                    path=path,
                    relative_path=relative_path,
                    display_name=path.name,
                    size_bytes=size_bytes,
                    kind=kind,
                )
            )

    return discovered


__all__ = [
    "SUPPORTED_FILE_TYPES",
    "SUPPORTED_SUFFIXES",
    "IGNORED_DIR_NAMES",
    "detect_kind",
    "discover_files",
]
