from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from backend.db import (
    REINDEX_REQUIRED_WORKSPACE_WARNING,
    REPAIRED_WORKSPACE_WARNING,
    WorkspaceStorageRecoveryError,
    _quarantine_database_files,
    clear_storage_warning,
    connect_sqlite,
    latest_storage_warning,
)
from backend.indexer.workspace import initialize_workspace
from backend.main import app


class WorkspaceStorageRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base = Path(self.temp_dir.name)
        self.workspace = self.base / "workspace"
        self.workspace.mkdir()
        self.db_path = self.workspace / ".fieldnotes" / "fieldnotes.db"
        self.client = TestClient(app)

    def tearDown(self) -> None:
        clear_storage_warning(self.db_path)
        self.temp_dir.cleanup()

    def test_truncated_db_without_sources_requires_reindex(self) -> None:
        initialize_workspace(self.workspace)
        self.db_path.write_bytes(b"not sqlite")
        with self.assertRaisesRegex(WorkspaceStorageRecoveryError, "requires re-indexing"):
            connect_sqlite(self.db_path)
        self.assertEqual(latest_storage_warning(self.db_path), REINDEX_REQUIRED_WORKSPACE_WARNING)
        self.assertTrue(any(path.name.startswith("fieldnotes.db.corrupt-") for path in self.db_path.parent.iterdir()))

    def test_corrupted_db_with_sources_rebuilds_successfully(self) -> None:
        initialize_workspace(self.workspace)
        (self.workspace / "notes.txt").write_text("alpha", encoding="utf-8")
        self.db_path.write_bytes(b"not sqlite")
        connection = connect_sqlite(self.db_path)
        try:
            row = connection.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(latest_storage_warning(self.db_path), REPAIRED_WORKSPACE_WARNING)
        self.assertEqual(row, 1)

    def test_wal_sidecars_are_quarantined_with_db(self) -> None:
        initialize_workspace(self.workspace)
        self.db_path.write_bytes(b"not sqlite")
        Path(f"{self.db_path}-wal").write_bytes(b"broken wal")
        Path(f"{self.db_path}-shm").write_bytes(b"broken shm")
        quarantined = _quarantine_database_files(self.db_path)
        quarantined_names = {path.name for path in quarantined}
        self.assertTrue(any(name.startswith("fieldnotes.db.corrupt-") for name in quarantined_names))
        self.assertTrue(any(name.startswith("fieldnotes.db-wal.corrupt-") for name in quarantined_names))
        self.assertTrue(any(name.startswith("fieldnotes.db-shm.corrupt-") for name in quarantined_names))

    def test_artifact_metadata_rehydrated_when_rebuild_unavailable(self) -> None:
        initialize_workspace(self.workspace)
        artifacts_dir = self.workspace / ".fieldnotes" / "artifacts"
        artifact_path = artifacts_dir / "answer_test_analysis.py"
        artifact_path.write_text("print('x')", encoding="utf-8")
        self.db_path.write_bytes(b"not sqlite")
        with self.assertRaises(WorkspaceStorageRecoveryError):
            connect_sqlite(self.db_path)
        connection = sqlite3.connect(self.db_path)
        try:
            row = connection.execute("SELECT kind, title, payload_path FROM artifacts").fetchone()
        finally:
            connection.close()
        self.assertEqual(row[0], "script")
        self.assertIn("Recovered script", row[1])
        self.assertEqual(row[2], str(artifact_path))

    def test_api_returns_stable_reindex_message_after_recovery_failure(self) -> None:
        initialize_workspace(self.workspace)
        self.db_path.write_bytes(b"not sqlite")
        client = TestClient(app, raise_server_exceptions=False)
        with patch(
            "backend.main.workspace_manager.get",
            return_value=type("Record", (), {"db_path": self.db_path, "artifacts_dir": self.workspace / ".fieldnotes" / "artifacts", "root": self.workspace})(),
        ):
            response = client.get("/notebook", params={"workspace_id": "ws"})
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["code"], "DATABASE_ERROR")
        self.assertEqual(response.json()["message"], REINDEX_REQUIRED_WORKSPACE_WARNING)

    def test_health_includes_storage_warning_after_repair(self) -> None:
        initialize_workspace(self.workspace)
        (self.workspace / "notes.txt").write_text("alpha", encoding="utf-8")
        self.db_path.write_bytes(b"not sqlite")
        connection = connect_sqlite(self.db_path)
        connection.close()
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["storage_warning"], REPAIRED_WORKSPACE_WARNING)

    def test_connection_setup_failure_closes_handle_before_recovery(self) -> None:
        fake_connection = Mock()
        fake_connection.execute.side_effect = [None, sqlite3.DatabaseError("file is not a database")]
        with patch("backend.db.sqlite3.connect", return_value=fake_connection):
            with self.assertRaises(sqlite3.DatabaseError):
                connect_sqlite(self.db_path, validate_integrity=False)
        fake_connection.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
