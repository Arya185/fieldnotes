from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("FIELDNOTES_USE_FAKE_LLM", "1")

from fastapi.testclient import TestClient

from backend.auth.drive_credentials import load_drive_credentials, save_drive_credentials
from backend.config import WORKSPACE_REGISTRY_DB_PATH
from backend.indexer.registry_database import RegistryDatabase
from backend.main import app
from backend.services.google_drive import (
    DriveFile,
    download_drive_file,
    list_drive_files,
)


class _FakeResponse:
    def __init__(self, status_code: int = 200, json_data=None, content: bytes = b""):
        self.status_code = status_code
        self._json = json_data
        self.content = content
        self.text = "" if json_data is None else str(json_data)

    def json(self):
        return self._json


class _FakeAsyncClient:
    def __init__(self, responses: list[_FakeResponse]):
        self._responses = list(responses)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def get(self, _url, **_kwargs):
        return self._responses.pop(0)

    async def post(self, _url, **_kwargs):
        return self._responses.pop(0)


class GoogleDriveServiceTests(unittest.TestCase):
    def test_list_drive_files_flags_importable_types(self) -> None:
        responses = [
            _FakeResponse(
                200,
                json_data={
                    "files": [
                        {"id": "1", "name": "Lecture Notes", "mimeType": "application/vnd.google-apps.document"},
                        {"id": "2", "name": "readings.pdf", "mimeType": "application/pdf"},
                        {"id": "3", "name": "video.mp4", "mimeType": "video/mp4"},
                    ]
                },
            )
        ]
        with patch("backend.services.google_drive.httpx.AsyncClient", lambda: _FakeAsyncClient(responses)):
            files = asyncio.run(list_drive_files("token", folder_id="folder_1"))

        by_id = {f.id: f for f in files}
        self.assertTrue(by_id["1"].importable)
        self.assertTrue(by_id["2"].importable)
        self.assertFalse(by_id["3"].importable)

    def test_download_drive_file_exports_google_doc_as_docx(self) -> None:
        responses = [_FakeResponse(200, content=b"docx-bytes")]
        drive_file = DriveFile(
            id="1", name="Lecture Notes", mime_type="application/vnd.google-apps.document", importable=True
        )
        with tempfile.TemporaryDirectory() as tmp:
            with patch("backend.services.google_drive.httpx.AsyncClient", lambda: _FakeAsyncClient(responses)):
                path = asyncio.run(download_drive_file("token", drive_file, Path(tmp)))
            self.assertEqual(path.name, "Lecture Notes.docx")
            self.assertEqual(path.read_bytes(), b"docx-bytes")

    def test_download_drive_file_passes_through_regular_pdf(self) -> None:
        responses = [_FakeResponse(200, content=b"%PDF-bytes")]
        drive_file = DriveFile(id="2", name="readings.pdf", mime_type="application/pdf", importable=True)
        with tempfile.TemporaryDirectory() as tmp:
            with patch("backend.services.google_drive.httpx.AsyncClient", lambda: _FakeAsyncClient(responses)):
                path = asyncio.run(download_drive_file("token", drive_file, Path(tmp)))
            self.assertEqual(path.name, "readings.pdf")
            self.assertEqual(path.read_bytes(), b"%PDF-bytes")


class GoogleDriveRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env_patcher = patch.dict(os.environ, {"FIELDNOTES_USE_FAKE_LLM": "1"}, clear=True)
        self.env_patcher.start()
        self.client = TestClient(app)
        registry = RegistryDatabase(WORKSPACE_REGISTRY_DB_PATH)
        connection = registry.connect()
        try:
            connection.execute("DELETE FROM google_drive_credentials WHERE user_id = 'local:local_admin'")
            connection.commit()
        finally:
            connection.close()

    def tearDown(self) -> None:
        self.env_patcher.stop()

    def test_status_reports_not_connected_by_default(self) -> None:
        response = self.client.get("/integrations/google-drive/status")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"connected": False})

    def test_files_endpoint_requires_connection(self) -> None:
        response = self.client.get("/integrations/google-drive/files")
        self.assertEqual(response.status_code, 401)

    def test_status_reports_connected_once_credentials_saved(self) -> None:
        registry = RegistryDatabase(WORKSPACE_REGISTRY_DB_PATH)
        connection = registry.connect()
        try:
            save_drive_credentials(
                connection,
                "local:local_admin",
                access_token="fake-access-token",
                refresh_token="fake-refresh-token",
                expires_at=None,
                scope="drive.readonly",
            )
            self.assertIsNotNone(load_drive_credentials(connection, "local:local_admin"))
        finally:
            connection.close()

        response = self.client.get("/integrations/google-drive/status")
        self.assertEqual(response.json(), {"connected": True})

        registry2 = RegistryDatabase(WORKSPACE_REGISTRY_DB_PATH)
        connection2 = registry2.connect()
        try:
            connection2.execute("DELETE FROM google_drive_credentials WHERE user_id = 'local:local_admin'")
            connection2.commit()
        finally:
            connection2.close()


class GoogleDriveImportPipelineTests(unittest.TestCase):
    """Verify an imported Drive file flows through the exact same indexing
    pipeline as a locally-added file — no parallel ingestion path."""

    def setUp(self) -> None:
        self.env_patcher = patch.dict(os.environ, {"FIELDNOTES_USE_FAKE_LLM": "1"}, clear=True)
        self.env_patcher.start()
        self.client = TestClient(app)
        self.temp_dir = tempfile.TemporaryDirectory()
        registry = RegistryDatabase(WORKSPACE_REGISTRY_DB_PATH)
        connection = registry.connect()
        try:
            save_drive_credentials(
                connection,
                "local:local_admin",
                access_token="fake-access-token",
                refresh_token="fake-refresh-token",
                expires_at=None,
                scope="drive.readonly",
            )
        finally:
            connection.close()

    def tearDown(self) -> None:
        self.env_patcher.stop()
        self.temp_dir.cleanup()
        registry = RegistryDatabase(WORKSPACE_REGISTRY_DB_PATH)
        connection = registry.connect()
        try:
            connection.execute("DELETE FROM google_drive_credentials WHERE user_id = 'local:local_admin'")
            connection.commit()
        finally:
            connection.close()

    def test_imported_drive_file_is_indexed_like_a_local_file(self) -> None:
        ws = Path(self.temp_dir.name) / "drive-import-workspace"
        ws.mkdir(parents=True, exist_ok=True)
        index = self.client.post("/index", json={"folder_path": str(ws)}).json()
        workspace_id = index["workspace_id"]
        self.client.get(index["events"])

        list_response = _FakeResponse(
            200,
            json_data={"files": [{"id": "drive_1", "name": "syllabus", "mimeType": "application/pdf"}]},
        )
        download_response = _FakeResponse(200, content=b"%PDF-1.4 fake pdf content")

        with patch(
            "backend.services.google_drive.httpx.AsyncClient",
            side_effect=[_FakeAsyncClient([list_response]), _FakeAsyncClient([download_response])],
        ):
            import_response = self.client.post(
                "/integrations/google-drive/import",
                json={"workspace_id": workspace_id, "file_ids": ["drive_1"]},
            )
        self.assertEqual(import_response.status_code, 200)
        self.assertEqual(import_response.json()["imported"], ["syllabus.pdf"])
        self.assertTrue((ws / "syllabus.pdf").exists())

        # Re-index the same folder through the normal endpoint: the imported
        # file must be picked up exactly like any other local file.
        reindex = self.client.post("/index", json={"folder_path": str(ws)}).json()
        self.client.get(reindex["events"])
        notebook = self.client.get("/notebook", params={"workspace_id": workspace_id}).json()
        self.assertGreaterEqual(notebook["file_count"], 1)


if __name__ == "__main__":
    unittest.main()
