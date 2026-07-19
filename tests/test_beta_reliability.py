from __future__ import annotations

import os
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")

from backend import config as backend_config
from backend.db import connect_sqlite
from backend.indexer.bm25 import tokenize
from backend.indexer.discovery import discover_files
from backend.sandbox import runner as sandbox_runner


class BetaReliabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_discovery_survives_stat_failure(self) -> None:
        target = self.base / "notes.md"
        target.write_text("alpha", encoding="utf-8")

        original_stat = Path.stat

        def flaky_stat(path: Path, *args, **kwargs):
            if path == target:
                raise PermissionError("denied")
            return original_stat(path, *args, **kwargs)

        with patch.object(Path, "stat", flaky_stat):
            discovered = discover_files(self.base)

        self.assertEqual(len(discovered), 1)
        self.assertEqual(discovered[0].relative_path, "notes.md")
        self.assertEqual(discovered[0].size_bytes, 0)

    def test_sqlite_connection_sets_busy_timeout_and_wal(self) -> None:
        connection = connect_sqlite(self.base / "fieldnotes.db")
        try:
            busy_timeout = connection.execute("PRAGMA busy_timeout").fetchone()[0]
            journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
        finally:
            connection.close()

        self.assertEqual(busy_timeout, 5000)
        self.assertEqual(str(journal_mode).lower(), "wal")

    def test_tokenize_preserves_hyphenated_identifiers(self) -> None:
        self.assertEqual(tokenize("Explain topic-00 and field-notes"), ["explain", "topic-00", "and", "field-notes"])

    def test_windows_platform_avoids_preexec_fn(self) -> None:
        artifacts_dir = self.base / "artifacts"
        captured: dict[str, object] = {}

        def fake_run(args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs
            result_path = Path(kwargs["env"]["FIELDNOTES_RESULT_PATH"])
            result_path.write_text('{"summary":"ok","metrics":{}}', encoding="utf-8")
            return type("Completed", (), {"returncode": 0, "stdout": "", "stderr": ""})()

        with patch.object(sandbox_runner, "resource", None), patch("subprocess.run", fake_run):
            result = sandbox_runner.run_generated_analysis(
                workspace_root=self.base,
                artifacts_dir=artifacts_dir,
                answer_id="windows_case",
                script_source=(
                    "import json, os\n"
                    "from pathlib import Path\n"
                    "Path(os.environ['FIELDNOTES_RESULT_PATH']).write_text('{\"summary\":\"ok\",\"metrics\":{}}', encoding='utf-8')\n"
                ),
            )

        self.assertEqual(result.result_payload["summary"], "ok")
        self.assertNotIn("preexec_fn", captured["kwargs"])

    def test_dotenv_values_are_loaded_without_overriding_shell(self) -> None:
        dotenv_path = self.base / ".env"
        dotenv_path.write_text(
            "OPENAI_API_KEY=dotenv-key\n"
            "FIELDNOTES_USE_FAKE_LLM=0\n"
            "OPENAI_MODEL=gpt-5\n",
            encoding="utf-8",
        )

        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, {}, clear=False))
            os.environ.pop("OPENAI_API_KEY", None)
            loaded = backend_config.load_project_dotenv(dotenv_path)
            self.assertTrue(loaded)
            self.assertEqual(os.environ["OPENAI_API_KEY"], "dotenv-key")

        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, {"OPENAI_API_KEY": "shell-key"}, clear=False))
            loaded = backend_config.load_project_dotenv(dotenv_path)
            self.assertTrue(loaded)
            self.assertEqual(os.environ["OPENAI_API_KEY"], "shell-key")

    def test_missing_dotenv_keeps_friendly_configuration_error(self) -> None:
        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, {}, clear=True))
            stack.enter_context(
                patch.multiple(
                    backend_config,
                    _validate_workspace_permissions=lambda: "ok",
                    _validate_sqlite_write_access=lambda: "ok",
                    _validate_sandbox_runtime=lambda: "ok",
                )
            )
            loaded = backend_config.load_project_dotenv(self.base / ".env")
            self.assertFalse(loaded)
            with self.assertRaises(backend_config.ConfigurationError) as exc:
                backend_config.validate_runtime_configuration()

        self.assertEqual(str(exc.exception), backend_config.format_missing_openai_api_key_message())


if __name__ == "__main__":
    unittest.main()
