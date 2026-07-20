from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.indexer.workspace_manager import WorkspaceManager


class WorkspaceRegistryRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base = Path(self.temp_dir.name)
        self.registry_dir = self.base / ".fieldnotes_registry"
        self.registry_dir.mkdir()
        self.registry_path = self.registry_dir / "workspaces.json"
        self.manager = WorkspaceManager(self.registry_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_missing_registry_returns_empty(self) -> None:
        self.assertEqual(self.manager._load_registry(), {})
        self.assertIsNone(self.manager.last_recovery_warning())

    def test_empty_registry_recovers_and_quarantines(self) -> None:
        self.registry_path.write_text("", encoding="utf-8")
        with self.assertLogs("fieldnotes.registry", level="WARNING"):
            registry = self.manager._load_registry()
        self.assertEqual(registry, {})
        self.assertEqual(self.registry_path.read_text(encoding="utf-8"), "{}")
        self.assertTrue(any(path.name.startswith("workspaces.corrupt-") for path in self.registry_dir.iterdir()))
        self.assertEqual(self.manager.last_recovery_warning(), "Registry file was empty and was recreated.")

    def test_malformed_registry_recovers_and_quarantines(self) -> None:
        self.registry_path.write_text("{bad json", encoding="utf-8")
        with self.assertLogs("fieldnotes.registry", level="WARNING"):
            registry = self.manager._load_registry()
        self.assertEqual(registry, {})
        self.assertEqual(json.loads(self.registry_path.read_text(encoding="utf-8")), {})
        self.assertTrue(any(path.name.startswith("workspaces.corrupt-") for path in self.registry_dir.iterdir()))

    def test_truncated_registry_recovers_and_quarantines(self) -> None:
        self.registry_path.write_text('{"ws":"', encoding="utf-8")
        with self.assertLogs("fieldnotes.registry", level="WARNING"):
            registry = self.manager._load_registry()
        self.assertEqual(registry, {})
        self.assertTrue(any(path.name.startswith("workspaces.corrupt-") for path in self.registry_dir.iterdir()))

    def test_permission_failure_on_load_recovers(self) -> None:
        self.registry_path.write_text("{}", encoding="utf-8")
        with (
            patch.object(Path, "read_text", side_effect=PermissionError("denied")),
            self.assertLogs("fieldnotes.registry", level="WARNING"),
        ):
            registry = self.manager._load_registry()
        self.assertEqual(registry, {})
        self.assertEqual(self.manager.last_recovery_warning(), "Registry file could not be read and was recreated.")

    def test_interrupted_write_does_not_break_register(self) -> None:
        workspace = self.base / "workspace"
        with patch.object(self.manager, "_atomic_write_json", side_effect=OSError("interrupted write")):
            record = self.manager.register(workspace)
        self.assertEqual(record.root, workspace.resolve())
        self.assertEqual(self.manager.last_recovery_warning(), "Workspace registry could not be updated on disk.")
        self.assertIn(record.workspace_id, self.manager._cache)

    def test_backup_created_before_overwrite(self) -> None:
        workspace_a = self.base / "workspace_a"
        workspace_b = self.base / "workspace_b"
        first = self.manager.register(workspace_a)
        second = self.manager.register(workspace_b)
        backup = self.manager.backup_path
        self.assertTrue(backup.exists())
        backup_payload = json.loads(backup.read_text(encoding="utf-8"))
        self.assertIn(first.workspace_id, backup_payload)
        self.assertNotIn(second.workspace_id, backup_payload)

    def test_registry_recreated_after_corruption_and_register_continues(self) -> None:
        self.registry_path.write_text("{", encoding="utf-8")
        workspace = self.base / "workspace"
        with self.assertLogs("fieldnotes.registry", level="WARNING"):
            record = self.manager.register(workspace)
        payload = json.loads(self.registry_path.read_text(encoding="utf-8"))
        self.assertEqual(payload, {record.workspace_id: str(workspace.resolve())})

    def test_invalid_registry_shape_recovers(self) -> None:
        self.registry_path.write_text('["wrong"]', encoding="utf-8")
        with self.assertLogs("fieldnotes.registry", level="WARNING"):
            registry = self.manager._load_registry()
        self.assertEqual(registry, {})
        self.assertEqual(self.manager.last_recovery_warning(), "Registry file contents were invalid and were recreated.")


if __name__ == "__main__":
    unittest.main()
