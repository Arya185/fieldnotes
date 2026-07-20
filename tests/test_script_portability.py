from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import release_check, run_benchmarks
from scripts.subprocess_utils import npm_command, npm_executable


class ScriptPortabilityTests(unittest.TestCase):
    def test_npm_command_uses_windows_wrapper(self) -> None:
        command = npm_command("run", "build", platform="nt", which=lambda name: f"C:/node/{name}")
        self.assertEqual(command, ["npm.cmd", "run", "build"])

    def test_npm_command_uses_posix_executable(self) -> None:
        command = npm_command("test", platform="posix", which=lambda name: f"/usr/bin/{name}")
        self.assertEqual(command, ["npm", "test"])

    def test_missing_npm_has_friendly_error(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "npm.cmd.*unavailable on PATH"):
            npm_executable(platform="nt", which=lambda _name: None)

    @patch("scripts.release_check.subprocess.run")
    @patch("scripts.release_check.subprocess.Popen")
    @patch("scripts.release_check.npm_command", return_value=["npm.cmd", "run", "build"])
    @patch("scripts.release_check._wait_for_backend_process")
    def test_release_check_uses_python_executable_and_path_script(
        self,
        _wait_for_backend: object,
        _npm_command: object,
        popen: object,
        run: object,
    ) -> None:
        process = _FakeProcess()
        popen.return_value = process  # type: ignore[attr-defined]
        run.side_effect = [  # type: ignore[attr-defined]
            subprocess.CompletedProcess(["npm.cmd"], 0, "", ""),
            subprocess.CompletedProcess([sys.executable], 0, "", ""),
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch("fastapi.testclient.TestClient", _ReleaseClient),
                patch.dict("os.environ", {"FIELDNOTES_USE_FAKE_LLM": "1"}, clear=True),
                patch.object(release_check, "RELEASE_ARTIFACTS_DIR", Path(temp_dir)),
            ):
                exit_code = release_check.main()

        self.assertEqual(exit_code, 0)
        self.assertEqual(popen.call_args.kwargs["cwd"], release_check.ROOT_DIR)  # type: ignore[attr-defined]
        benchmark_call = run.call_args_list[1]  # type: ignore[attr-defined]
        self.assertEqual(benchmark_call.args[0][0], sys.executable)
        self.assertEqual(benchmark_call.args[0][1], str(release_check.ROOT_DIR / "scripts" / "run_benchmarks.py"))
        self.assertEqual(benchmark_call.kwargs["cwd"], release_check.ROOT_DIR)

    @patch("scripts.run_benchmarks.npm_command", return_value=["npm.cmd", "run", "build"])
    def test_benchmark_frontend_command_has_explicit_working_directory(
        self,
        _npm_command: object,
    ) -> None:
        calls: list[tuple[list[str], dict]] = []

        def failing_runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            calls.append((command, kwargs))
            return subprocess.CompletedProcess(command, 1, "", "missing")

        with self.assertRaisesRegex(RuntimeError, "Frontend build benchmark failed"):
            run_benchmarks.run_benchmarks(command_runner=failing_runner)
        self.assertEqual(calls[0][0], ["npm.cmd", "run", "build"])
        self.assertEqual(calls[0][1]["cwd"], run_benchmarks.FRONTEND_DIR)


class _FakeProcess:
    def __init__(self) -> None:
        self.stderr = None
        self.stdout = None

    def poll(self) -> None:
        return None

    def terminate(self) -> None:
        pass

    def wait(self, timeout: int) -> None:
        return None

    def kill(self) -> None:
        pass


class _ReleaseClient:
    def __init__(self, _app: object) -> None:
        self.workspace_id = "workspace_test"

    def get(self, path: str, params: dict | None = None) -> _Response:
        if path == "/health":
            return _Response({"status": "ok", "version": release_check.expected_version(), "mode": "fake", "startup": "healthy"})
        if path == "/openapi.json":
            return _Response({"info": {"version": release_check.expected_version()}})
        if path == "/notebook":
            return _Response({"artifacts": [{"id": "artifact"}]})
        if path.startswith("/source/"):
            return _Response({"text": "source", "label": "notes.md"})
        if path == "/index/events/run_test":
            return _SseResponse([{ "event": "index_complete" }])
        raise AssertionError(path)

    def post(self, path: str, json: dict) -> _Response:
        if path == "/index":
            return _Response({"events": "/index/events/run_test", "workspace_id": self.workspace_id})
        if path == "/ask":
            return _SseResponse(
                [
                    {"event": "citations", "chips": [{"chip_type": "document", "anchor": "file_a#block1/b1"}]},
                    {"event": "done"},
                ]
            )
        if path == "/quiz/start":
            return _SseResponse([{ "event": "question", "attempt_id": "attempt", "source_anchor": "file_a#block1/b1" }])
        if path == "/quiz/answer":
            return _SseResponse([{ "event": "graded" }, { "event": "quiz_done" }])
        raise AssertionError(path)


class _Response:
    status_code = 200

    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def json(self) -> dict:
        return self._payload


class _SseResponse(_Response):
    def __init__(self, events: list[dict]) -> None:
        self.text = "\n\n".join(f"data: {__import__('json').dumps(event)}" for event in events)
