from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from backend.auth.cookies import (
    CSRF_COOKIE_NAME,
    OAUTH_STATE_COOKIE_NAME,
    REFRESH_COOKIE_NAME,
    SESSION_COOKIE_NAME,
)
from backend.auth.drive_credentials import (
    TOKEN_ENCRYPTION_KEY_ENV,
    load_drive_credentials,
    save_drive_credentials,
    validate_token_encryption_configuration,
)
from backend.auth.jwt import create_access_token
from backend.auth.security import auth_config, rate_limiter, validate_auth_runtime_configuration
from backend.indexer.registry_database import RegistryDatabase
from backend.indexer.workspace_manager import workspace_manager
from backend.main import app


def bearer_headers(subject: str) -> dict[str, str]:
    token = create_access_token(
        subject,
        f"{subject}@example.com",
        "local",
        subject,
        role="viewer",
    )
    return {"Authorization": f"Bearer {token}"}


class Phase1SecurityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base = Path(self.temp_dir.name)
        self.env_patcher = patch.dict(
            os.environ,
            {
                "FIELDNOTES_USE_FAKE_LLM": "1",
                "FIELDNOTES_JWT_SECRET": "test-secret",
                TOKEN_ENCRYPTION_KEY_ENV: "Z5c5qwSHl46AMkYhNpkx0A3VPl08zmvlaR271GGBq4w=",
                # This file owns the rate-limiting tests, so it needs
                # enforcement actually active — undo the suite-wide
                # opt-out set in tests/__init__.py.
                "FIELDNOTES_RATE_LIMIT_DISABLED": "0",
            },
            clear=False,
        )
        self.env_patcher.start()
        auth_config.refresh()
        rate_limiter._buckets.clear()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.env_patcher.stop()
        auth_config.refresh()
        rate_limiter._buckets.clear()
        self.temp_dir.cleanup()

    def test_oauth_callback_rejects_mismatched_state(self) -> None:
        with patch.dict(os.environ, {"FIELDNOTES_AUTH_ENABLED": "1"}, clear=False):
            auth_config.refresh()
            response = self.client.get("/auth/login/google")
            self.assertEqual(response.status_code, 200)
            callback = self.client.get(
                "/auth/callback",
                params={"provider": "google", "code": "abc", "state": "wrong-state"},
            )
            self.assertEqual(callback.status_code, 400)
            self.assertIn("OAuth state mismatch", callback.text)

    def test_oauth_callback_is_single_use_and_clears_state_cookie(self) -> None:
        with patch.dict(os.environ, {"FIELDNOTES_AUTH_ENABLED": "1"}, clear=False):
            auth_config.refresh()
            login = self.client.get("/auth/login/google")
            self.assertEqual(login.status_code, 200)
            state_cookie = self.client.cookies.get(OAUTH_STATE_COOKIE_NAME)
            self.assertIsNotNone(state_cookie)
            redirect_url = login.json()["redirect_url"]
            state = redirect_url.split("state=")[1].split("&", 1)[0]

            with patch("backend.auth.router._exchange_token", new=AsyncMock(return_value={"access_token": "token"})), patch(
                "backend.auth.router._fetch_google_userinfo",
                new=AsyncMock(return_value={"sub": "user-1", "email": "user@example.com", "name": "User One"}),
            ):
                callback = self.client.get(
                    "/auth/callback",
                    params={"provider": "google", "code": "abc", "state": state},
                    follow_redirects=False,
                )
            self.assertEqual(callback.status_code, 307)
            set_cookie_headers = callback.headers.get_list("set-cookie")
            self.assertTrue(any(OAUTH_STATE_COOKIE_NAME in value and "Max-Age=0" in value for value in set_cookie_headers))
            second = self.client.get(
                "/auth/callback",
                params={"provider": "google", "code": "abc", "state": state},
            )
            self.assertEqual(second.status_code, 400)

    def test_csrf_required_for_cookie_authenticated_mutation(self) -> None:
        with patch.dict(os.environ, {"FIELDNOTES_AUTH_ENABLED": "1"}, clear=False):
            auth_config.refresh()
            self.client.cookies.set(SESSION_COOKIE_NAME, "session-token")
            self.client.cookies.set(CSRF_COOKIE_NAME, "csrf-token")
            rejected = self.client.post("/auth/logout")
            self.assertEqual(rejected.status_code, 403)

            accepted = self.client.post(
                "/auth/logout",
                headers={"X-CSRF-Token": "csrf-token"},
            )
            self.assertEqual(accepted.status_code, 200)

    def test_cookie_names_are_hardened_and_csrf_cookie_is_issued_without_httponly(self) -> None:
        with patch.dict(os.environ, {"FIELDNOTES_AUTH_ENABLED": "1"}, clear=False):
            auth_config.refresh()
            login = self.client.get("/auth/login/google")
            self.assertEqual(login.status_code, 200)
            self.assertTrue(SESSION_COOKIE_NAME.startswith("__Host-"))
            self.assertTrue(REFRESH_COOKIE_NAME.startswith("__Host-"))
            self.assertTrue(CSRF_COOKIE_NAME.startswith("__Host-"))

            redirect_url = login.json()["redirect_url"]
            state = redirect_url.split("state=")[1].split("&", 1)[0]
            with patch("backend.auth.router._exchange_token", new=AsyncMock(return_value={"access_token": "token"})), patch(
                "backend.auth.router._fetch_google_userinfo",
                new=AsyncMock(return_value={"sub": "user-2", "email": "user2@example.com", "name": "User Two"}),
            ):
                callback = self.client.get(
                    "/auth/callback",
                    params={"provider": "google", "code": "abc", "state": state},
                    follow_redirects=False,
                )
            set_cookie_headers = callback.headers.get_list("set-cookie")
            csrf_headers = [value for value in set_cookie_headers if CSRF_COOKIE_NAME in value]
            self.assertEqual(len(csrf_headers), 1)
            self.assertNotIn("HttpOnly", csrf_headers[0])

    def test_auth_mode_requires_explicit_flag_in_production(self) -> None:
        with patch.dict(os.environ, {"FIELDNOTES_ENV": "production"}, clear=False):
            os.environ.pop("FIELDNOTES_AUTH_ENABLED", None)
            with self.assertRaisesRegex(RuntimeError, "FIELDNOTES_AUTH_ENABLED"):
                validate_auth_runtime_configuration()

    def test_token_encryption_required_in_production(self) -> None:
        with patch.dict(
            os.environ,
            {"FIELDNOTES_ENV": "production", "FIELDNOTES_AUTH_ENABLED": "1"},
            clear=False,
        ):
            os.environ.pop(TOKEN_ENCRYPTION_KEY_ENV, None)
            with self.assertRaisesRegex(RuntimeError, TOKEN_ENCRYPTION_KEY_ENV):
                validate_token_encryption_configuration(require_for_startup=True)

    def test_drive_credentials_are_encrypted_at_rest(self) -> None:
        registry = RegistryDatabase(self.base / "registry.db")
        connection = registry.connect()
        try:
            save_drive_credentials(
                connection,
                "local:local_admin",
                access_token="plain-access",
                refresh_token="plain-refresh",
                expires_at=None,
                scope="drive.readonly",
            )
            row = connection.execute(
                "SELECT access_token, refresh_token FROM google_drive_credentials WHERE user_id = ?",
                ("local:local_admin",),
            ).fetchone()
            self.assertNotEqual(row["access_token"], "plain-access")
            self.assertNotEqual(row["refresh_token"], "plain-refresh")
            loaded = load_drive_credentials(connection, "local:local_admin")
            self.assertEqual(loaded["access_token"], "plain-access")
            self.assertEqual(loaded["refresh_token"], "plain-refresh")
        finally:
            connection.close()

    def test_registry_upgrade_removes_legacy_plaintext_drive_tokens(self) -> None:
        db_path = self.base / "legacy-registry.db"
        connection = sqlite3.connect(db_path)
        try:
            for sql_path in RegistryDatabase(db_path).SQL_FILES if False else []:
                pass
        finally:
            connection.close()

        raw = sqlite3.connect(db_path)
        try:
            raw.executescript((Path("backend/sql/registry.sql")).read_text(encoding="utf-8"))
            raw.executescript((Path("backend/sql/workspace.sql")).read_text(encoding="utf-8"))
            raw.execute("DELETE FROM schema_version")
            raw.execute("INSERT INTO schema_version (version) VALUES (1)")
            raw.execute(
                """
                INSERT INTO google_drive_credentials (
                    user_id, access_token, refresh_token, expires_at, scope, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                ("legacy-user", "plain-access", "plain-refresh", None, "drive.readonly", "2026-08-05T00:00:00+00:00"),
            )
            raw.commit()
        finally:
            raw.close()

        migrated = RegistryDatabase(db_path)
        conn2 = migrated.connect()
        try:
            count = conn2.execute("SELECT COUNT(*) AS count FROM google_drive_credentials").fetchone()["count"]
            version = conn2.execute(
                "SELECT version FROM schema_version ORDER BY rowid DESC LIMIT 1"
            ).fetchone()["version"]
            self.assertEqual(count, 0)
            self.assertEqual(version, 2)
        finally:
            conn2.close()

    def test_drive_import_requires_workspace_membership(self) -> None:
        with patch.dict(os.environ, {"FIELDNOTES_AUTH_ENABLED": "1"}, clear=False):
            auth_config.refresh()
            workspace_root = self.base / "workspace-authz"
            workspace_root.mkdir(parents=True, exist_ok=True)
            owner = {
                "user_id": "owner-user",
                "email": "owner@example.com",
                "name": "Owner",
                "provider": "local",
                "provider_id": "owner-user",
                "role": "owner",
            }
            workspace = workspace_manager.register(workspace_root, creator=owner)

            registry = RegistryDatabase((workspace_manager.registry_path))
            connection = registry.connect()
            try:
                save_drive_credentials(
                    connection,
                    "local:attacker-user",
                    access_token="fake-access-token",
                    refresh_token="fake-refresh-token",
                    expires_at=None,
                    scope="drive.readonly",
                )
            finally:
                connection.close()

            response = self.client.post(
                "/integrations/google-drive/import",
                json={"workspace_id": workspace.workspace_id, "file_ids": ["file-1"]},
                headers=bearer_headers("local:attacker-user"),
            )
            self.assertEqual(response.status_code, 403)

    def test_study_plan_create_list_and_get_use_same_workspace_db(self) -> None:
        workspace_root = self.base / "workspace-plans"
        workspace_root.mkdir(parents=True, exist_ok=True)
        index = self.client.post("/index", json={"folder_path": str(workspace_root)}).json()
        workspace_id = index["workspace_id"]
        self.client.get(index["events"])

        created = self.client.post(
            "/study-plans",
            json={
                "workspace_id": workspace_id,
                "title": "Plan",
                "exam_date": "2099-01-01",
                "hours_per_day": 1.0,
                "pace": "medium",
            },
        )
        self.assertEqual(created.status_code, 200)
        plan_id = created.json()["plan_id"]

        listed = self.client.get("/study-plans", params={"workspace_id": workspace_id})
        self.assertEqual(listed.status_code, 200)
        plan_ids = {item["id"] for item in listed.json()}
        self.assertIn(plan_id, plan_ids)

        fetched = self.client.get(
            f"/study-plans/{plan_id}",
            params={"workspace_id": workspace_id},
        )
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(fetched.json()["plan_id"], plan_id)
        self.assertIn("items", fetched.json())

    def test_auth_login_rate_limit_trips(self) -> None:
        with patch.dict(os.environ, {"FIELDNOTES_AUTH_ENABLED": "1"}, clear=False):
            auth_config.refresh()
            for _ in range(10):
                response = self.client.get("/auth/login/google")
                self.assertEqual(response.status_code, 200)
            limited = self.client.get("/auth/login/google")
            self.assertEqual(limited.status_code, 429)

    def test_google_drive_files_rate_limit_trips(self) -> None:
        registry = RegistryDatabase(workspace_manager.registry_path)
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

        with patch("backend.routers.integrations.list_drive_files", new=AsyncMock(return_value=[])):
            for _ in range(12):
                response = self.client.get("/integrations/google-drive/files")
                self.assertEqual(response.status_code, 200)
            limited = self.client.get("/integrations/google-drive/files")
            self.assertEqual(limited.status_code, 429)


if __name__ == "__main__":
    unittest.main()
