from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from backend.indexer.workspace_manager import WorkspaceManager


class WorkspaceRegistryRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base = Path(self.temp_dir.name)
        self.registry_dir = self.base / ".fieldnotes_registry"
        self.registry_dir.mkdir()
        self.registry_path = self.registry_dir / "fieldnotes_registry.db"
        self.legacy_registry_path = self.registry_dir / "workspaces.json"
        self.manager = WorkspaceManager(self.registry_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_missing_registry_returns_empty_list(self) -> None:
        self.assertEqual(self.manager.list_workspaces(), [])
        self.assertIsNone(self.manager.last_recovery_warning())

    def test_register_creates_workspace_and_metadata(self) -> None:
        workspace = self.base / "workspace"
        record = self.manager.register(workspace)
        self.assertEqual(record.root, workspace.resolve())
        self.assertTrue((workspace / ".fieldnotes" / "workspace.json").exists())
        self.assertEqual(self.manager.get(record.workspace_id).workspace_id, record.workspace_id)

    def test_register_same_workspace_returns_same_id(self) -> None:
        workspace = self.base / "workspace"
        first = self.manager.register(workspace)
        second = self.manager.register(workspace)
        self.assertEqual(first.workspace_id, second.workspace_id)

    def test_legacy_registry_json_migrates_to_db(self) -> None:
        workspace = self.base / "workspace"
        workspace.resolve()
        legacy_payload = {"abc123": str(workspace.resolve())}
        self.legacy_registry_path.write_text(json.dumps(legacy_payload), encoding="utf-8")

        migrated_manager = WorkspaceManager(self.registry_path)
        self.assertFalse(self.legacy_registry_path.exists())
        record = migrated_manager.get("abc123")
        self.assertIsNotNone(record)
        self.assertEqual(record.root, workspace.resolve())

    def test_corrupted_registry_db_is_recovered(self) -> None:
        self.registry_path.write_bytes(b"not a sqlite file")
        recovered_manager = WorkspaceManager(self.registry_path)
        self.assertEqual(recovered_manager.list_workspaces(), [])
        self.assertTrue(self.registry_path.exists())
        self.assertEqual(
            recovered_manager.last_recovery_warning(),
            "Registry database could not be read and was recreated.",
        )

    def test_registry_path_aliasing_from_legacy_json_name(self) -> None:
        json_named_path = self.registry_dir / "workspaces.json"
        manager = WorkspaceManager(json_named_path)
        self.assertEqual(manager.registry_path, self.registry_dir / "fieldnotes_registry.db")


if __name__ == "__main__":
    unittest.main()
