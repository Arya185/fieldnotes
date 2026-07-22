from __future__ import annotations

import os
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

os.environ.setdefault("FIELDNOTES_USE_FAKE_LLM", "1")

from backend import config as backend_config
from backend.db import connect_sqlite
from backend.indexer.bm25 import tokenize
from backend.indexer.discovery import discover_files
from backend.sandbox.containment import SandboxLimitExceeded, SandboxPolicy
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

    def test_windows_platform_uses_native_runner_without_preexec_fn(self) -> None:
        artifacts_dir = self.base / "artifacts"
        captured: dict[str, object] = {}

        def fake_runner(*, command, cwd, env, policy, preexec_fn):
            captured["command"] = command
            captured["cwd"] = cwd
            captured["env"] = env
            captured["policy"] = policy
            captured["preexec_fn"] = preexec_fn
            result_path = Path(env["FIELDNOTES_RESULT_PATH"])
            result_path.write_text('{"summary":"ok","metrics":{}}', encoding="utf-8")
            return type("Completed", (), {"returncode": 0, "stdout": "", "stderr": ""})()

        with patch.object(sandbox_runner, "resource", None), patch.object(sandbox_runner, "run_platform_sandbox", fake_runner):
            result = sandbox_runner.run_generated_analysis(
                workspace_root=self.base,
                artifacts_dir=artifacts_dir,
                answer_id="windows_case",
                script_source=(
                    "write_result({'summary': 'ok', 'metrics': {}})\n"
                ),
            )

        self.assertEqual(result.result_payload["summary"], "ok")
        self.assertIsNone(captured["preexec_fn"])
        self.assertEqual(captured["cwd"], self.base)
        self.assertEqual(captured["command"][1], "-I")
        self.assertIsInstance(captured["policy"], SandboxPolicy)
        self.assertEqual(captured["policy"].max_processes, 1)
        self.assertEqual(captured["policy"].memory_bytes, sandbox_runner.DEFAULT_MEMORY_BYTES)

    def test_sandbox_propagates_thread_limit_environment(self) -> None:
        artifacts_dir = self.base / "artifacts"
        captured: dict[str, object] = {}

        def fake_runner(*, command, cwd, env, policy, preexec_fn):
            captured["env"] = env
            result_path = Path(env["FIELDNOTES_RESULT_PATH"])
            result_path.write_text('{"summary":"ok","metrics":{}}', encoding="utf-8")
            return type("Completed", (), {"returncode": 0, "stdout": "", "stderr": ""})()

        with (
            patch.object(sandbox_runner, "resource", None),
            patch.object(sandbox_runner, "run_platform_sandbox", fake_runner),
            patch.dict(
                os.environ,
                {
                    "OPENBLAS_NUM_THREADS": "1",
                    "OMP_NUM_THREADS": "1",
                    "MKL_NUM_THREADS": "1",
                    "NUMEXPR_NUM_THREADS": "1",
                },
                clear=False,
            ),
        ):
            sandbox_runner.run_generated_analysis(
                workspace_root=self.base,
                artifacts_dir=artifacts_dir,
                answer_id="thread_limit_case",
                script_source="write_result({'summary': 'ok', 'metrics': {}})\n",
            )

        sandbox_env = captured["env"]
        self.assertEqual(sandbox_env["OPENBLAS_NUM_THREADS"], "1")
        self.assertEqual(sandbox_env["OMP_NUM_THREADS"], "1")
        self.assertEqual(sandbox_env["MKL_NUM_THREADS"], "1")
        self.assertEqual(sandbox_env["NUMEXPR_NUM_THREADS"], "1")

    def test_startup_sandbox_validation_uses_same_thread_limit_environment(self) -> None:
        captured: dict[str, object] = {}

        def fake_run(command, *, cwd, env, capture_output, text, timeout, check):
            captured["command"] = command
            captured["cwd"] = cwd
            captured["env"] = env
            result_path = Path(env["FIELDNOTES_RESULT_PATH"])
            result_path.write_text('{"ok": true}', encoding="utf-8")
            return type("Completed", (), {"returncode": 0, "stdout": "", "stderr": ""})()

        with (
            patch.dict(
                os.environ,
                {
                    "OPENBLAS_NUM_THREADS": "1",
                    "OMP_NUM_THREADS": "1",
                    "MKL_NUM_THREADS": "1",
                    "NUMEXPR_NUM_THREADS": "1",
                },
                clear=False,
            ),
            patch("backend.config.subprocess.run", side_effect=fake_run),
        ):
            self.assertEqual(backend_config._validate_sandbox_runtime(), "ok")

        sandbox_env = captured["env"]
        self.assertEqual(sandbox_env["OPENBLAS_NUM_THREADS"], "1")
        self.assertEqual(sandbox_env["OMP_NUM_THREADS"], "1")
        self.assertEqual(sandbox_env["MKL_NUM_THREADS"], "1")
        self.assertEqual(sandbox_env["NUMEXPR_NUM_THREADS"], "1")

    def test_windows_limit_failure_surfaces_clean_runtime_error(self) -> None:
        artifacts_dir = self.base / "artifacts"

        def fake_runner(*, command, cwd, env, policy, preexec_fn):
            raise SandboxLimitExceeded("Analysis sandbox timed out after 1s")

        with patch.object(sandbox_runner, "resource", None), patch.object(sandbox_runner, "run_platform_sandbox", fake_runner):
            with self.assertRaisesRegex(RuntimeError, "timed out"):
                sandbox_runner.run_generated_analysis(
                    workspace_root=self.base,
                    artifacts_dir=artifacts_dir,
                    answer_id="windows_limit",
                    script_source="while True:\n    pass\n",
                    timeout_seconds=1,
                )

        self.assertFalse((artifacts_dir / "windows_limit_analysis.py").exists())
        self.assertFalse((artifacts_dir / "windows_limit_result.json").exists())
        self.assertFalse((artifacts_dir / "windows_limit_chart.png").exists())

    def test_dotenv_values_are_loaded_without_overriding_shell(self) -> None:
        dotenv_path = self.base / ".env"
        dotenv_key = str(uuid4())
        shell_key = str(uuid4())
        dotenv_path.write_text(
            f"OPENAI_API_KEY={dotenv_key}\n"
            "FIELDNOTES_USE_FAKE_LLM=0\n"
            "OPENAI_MODEL=gpt-5\n",
            encoding="utf-8",
        )

        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, {}, clear=False))
            os.environ.pop("OPENAI_API_KEY", None)
            loaded = backend_config.load_project_dotenv(dotenv_path)
            self.assertTrue(loaded)
            self.assertEqual(os.environ["OPENAI_API_KEY"], dotenv_key)

        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, {"OPENAI_API_KEY": shell_key}, clear=False))
            loaded = backend_config.load_project_dotenv(dotenv_path)
            self.assertTrue(loaded)
            self.assertEqual(os.environ["OPENAI_API_KEY"], shell_key)

    def test_missing_dotenv_falls_back_to_fake_mode(self) -> None:
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
            with self.assertLogs("fieldnotes.startup", level="WARNING") as logs:
                diagnostics = backend_config.validate_runtime_configuration()
            self.assertEqual(os.environ["FIELDNOTES_USE_FAKE_LLM"], "1")

        self.assertEqual(diagnostics.startup_checks["responses_api"], "ok")
        self.assertTrue(any("No OPENAI_API_KEY detected." in line for line in logs.output))
        self.assertTrue(any("Falling back to fake LLM mode." in line for line in logs.output))

    def test_openai_api_key_takes_precedence_over_fake_flag(self) -> None:
        live_key = str(uuid4())
        with ExitStack() as stack:
            stack.enter_context(
                patch.dict(
                    os.environ,
                    {"OPENAI_API_KEY": live_key, "FIELDNOTES_USE_FAKE_LLM": "1"},
                    clear=True,
                )
            )
            stack.enter_context(
                patch.multiple(
                    backend_config,
                    _validate_workspace_permissions=lambda: "ok",
                    _validate_sqlite_write_access=lambda: "ok",
                    _validate_sandbox_runtime=lambda: "ok",
                )
            )
            with self.assertLogs("fieldnotes.startup", level="INFO") as logs:
                diagnostics = backend_config.validate_runtime_configuration()
            self.assertEqual(os.environ["FIELDNOTES_USE_FAKE_LLM"], "0")

        self.assertEqual(diagnostics.startup_checks["responses_api"], "configured")
        self.assertTrue(any("OpenAI API detected. Running in live mode." in line for line in logs.output))

    def test_openai_timeout_seconds_can_be_configured_from_env(self) -> None:
        with patch.dict(os.environ, {"FIELDNOTES_OPENAI_TIMEOUT_SECONDS": "75"}, clear=False):
            client = __import__("backend.agent.llm", fromlist=["LLMClient"]).LLMClient(
                model="gpt-live",
                client=object(),
            )

        self.assertEqual(client.timeout_seconds, 75.0)


if __name__ == "__main__":
    unittest.main()
