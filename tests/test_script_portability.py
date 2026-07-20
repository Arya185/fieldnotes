from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

from scripts import exit_phase0
from scripts import release_check, run_benchmarks
from scripts.subprocess_utils import npm_command, npm_executable


class ScriptPortabilityTests(unittest.TestCase):
    def test_npm_command_uses_windows_wrapper(self) -> None:
        command = npm_command(
            "run",
            "build",
            platform="nt",
            which=lambda name: "C:/node/npm.cmd" if name == "npm.cmd" else None,
        )
        self.assertEqual(command, ["C:/node/npm.cmd", "run", "build"])

    def test_npm_command_uses_posix_executable(self) -> None:
        command = npm_command("test", platform="posix", which=lambda name: "/usr/local/bin/npm" if name == "npm" else None)
        self.assertEqual(command, ["/usr/local/bin/npm", "test"])

    def test_missing_npm_has_friendly_error(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "Searched executable names: npm.cmd, npm, npx, npx.cmd"):
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
                patch.dict("os.environ", {"FIELDNOTES_USE_FAKE_LLM": "1"}, clear=True),
                patch.object(release_check, "RELEASE_ARTIFACTS_DIR", Path(temp_dir)),
                patch.object(release_check, "_wait_for_backend_http", return_value=_health_payload()),
                patch.object(release_check, "_request_json", side_effect=_release_request_json),
                patch.object(release_check, "_request_sse", side_effect=_release_request_sse),
            ):
                exit_code = release_check.main()

        self.assertEqual(exit_code, 0)
        self.assertEqual(popen.call_args.kwargs["cwd"], release_check.ROOT_DIR)  # type: ignore[attr-defined]
        benchmark_call = run.call_args_list[1]  # type: ignore[attr-defined]
        self.assertEqual(benchmark_call.args[0][0], sys.executable)
        self.assertEqual(benchmark_call.args[0][1], str(release_check.ROOT_DIR / "scripts" / "run_benchmarks.py"))
        self.assertEqual(benchmark_call.kwargs["cwd"], release_check.ROOT_DIR)

    def test_request_json_reports_http_failure_with_endpoint_status_body_and_time(self) -> None:
        with patch.object(
            release_check,
            "_request_text",
            return_value={"status": 500, "body_text": '{"detail":"boom"}', "elapsed_ms": 123},
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                r"/health failed status=500 elapsed_ms=123 body=\{\"detail\":\"boom\"\}",
            ):
                release_check._request_json("http://127.0.0.1:8765", "GET", "/health")

    def test_wait_for_backend_http_retries_until_health_ok(self) -> None:
        process = _FakeProcess()
        calls = [
            RuntimeError("/health request failed after 10ms: refused"),
            {"status": 200, "body": _health_payload(), "body_text": '{"status":"ok"}', "elapsed_ms": 5},
        ]

        def fake_request(*_args: object, **_kwargs: object) -> dict:
            result = calls.pop(0)
            if isinstance(result, Exception):
                raise result
            return result

        with (
            patch.object(release_check, "_request_json", side_effect=fake_request),
            patch("scripts.release_check.time.sleep"),
        ):
            payload = release_check._wait_for_backend_http(process, "http://127.0.0.1:8765")

        self.assertEqual(payload["status"], "ok")

    def test_terminate_backend_process_kills_after_timeout(self) -> None:
        process = _FakeTimeoutProcess()
        release_check._terminate_backend_process(process)
        self.assertTrue(process.terminated)
        self.assertTrue(process.killed)

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

    @patch("scripts.exit_phase0.verify_responses_api_connection")
    def test_phase0_reports_live_api_skipped_without_credentials(self, probe: object) -> None:
        output = StringIO()
        with (
            patch("sys.stdout", output),
            patch.object(exit_phase0, "verify_configuration"),
            patch.object(exit_phase0, "verify_startup_and_health"),
            patch.object(exit_phase0, "verify_fake_mode"),
            patch.object(exit_phase0, "verify_live_validation"),
            patch.object(exit_phase0, "verify_responses_configuration"),
            patch.dict("os.environ", {"FIELDNOTES_USE_FAKE_LLM": "0"}, clear=True),
        ):
            exit_code = exit_phase0.main()

        self.assertEqual(exit_code, 0)
        self.assertIn("LIVE API", output.getvalue())
        self.assertIn("SKIPPED", output.getvalue())
        probe.assert_not_called()  # type: ignore[attr-defined]

    @patch("scripts.exit_phase0.verify_responses_api_connection")
    def test_phase0_reports_live_api_ok_with_credentials(self, probe: object) -> None:
        probe.return_value = type("Probe", (), {"model": "gpt-5"})()  # type: ignore[attr-defined]
        output = StringIO()
        with (
            patch("sys.stdout", output),
            patch.object(exit_phase0, "verify_configuration"),
            patch.object(exit_phase0, "verify_startup_and_health"),
            patch.object(exit_phase0, "verify_fake_mode"),
            patch.object(exit_phase0, "verify_live_validation"),
            patch.object(exit_phase0, "verify_responses_configuration"),
            patch.dict("os.environ", {"OPENAI_API_KEY": "test-key", "OPENAI_MODEL": "gpt-5"}, clear=True),
        ):
            exit_code = exit_phase0.main()

        self.assertEqual(exit_code, 0)
        self.assertIn("LIVE API", output.getvalue())
        self.assertIn("OK", output.getvalue())

    def test_release_workflow_keeps_fake_mode_and_adds_secret_gated_live_job(self) -> None:
        workflow = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "release.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("FIELDNOTES_USE_FAKE_LLM: \"1\"", workflow)
        self.assertIn("live-openai-validation", workflow)
        self.assertIn("if: ${{ secrets.OPENAI_API_KEY != '' }}", workflow)
        self.assertIn("python scripts/exit_phase0.py", workflow)
        self.assertIn("python -m unittest tests.test_live_responses_api_integration", workflow)


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


class _FakeTimeoutProcess(_FakeProcess):
    def __init__(self) -> None:
        super().__init__()
        self.terminated = False
        self.killed = False

    def terminate(self) -> None:
        self.terminated = True

    def wait(self, timeout: int) -> None:
        if not self.killed:
            raise subprocess.TimeoutExpired(cmd="uvicorn", timeout=timeout)

    def kill(self) -> None:
        self.killed = True


def _health_payload() -> dict[str, str]:
    return {
        "status": "ok",
        "version": release_check.expected_version(),
        "mode": "fake",
        "startup": "healthy",
    }


def _release_request_json(
    _base_url: str,
    method: str,
    path: str,
    body: dict | None = None,
    *,
    params: dict[str, str] | None = None,
    timeout: float = 20.0,
) -> dict:
    del body, params, timeout
    if method == "GET" and path == "/openapi.json":
        return {"status": 200, "body": {"info": {"version": release_check.expected_version()}}, "body_text": "", "elapsed_ms": 1}
    if method == "POST" and path == "/index":
        return {"status": 200, "body": {"events": "/index/events/run_test", "workspace_id": "workspace_test"}, "body_text": "", "elapsed_ms": 1}
    if method == "GET" and path == "/notebook":
        return {"status": 200, "body": {"artifacts": [{"id": "artifact"}]}, "body_text": "", "elapsed_ms": 1}
    if method == "GET" and path.startswith("/source/"):
        return {"status": 200, "body": {"text": "source", "label": "notes.md"}, "body_text": "", "elapsed_ms": 1}
    raise AssertionError((method, path))


def _release_request_sse(
    _base_url: str,
    method: str,
    path: str,
    body: dict | None = None,
    *,
    params: dict[str, str] | None = None,
    timeout: float = 60.0,
) -> list[dict]:
    del body, params, timeout
    if method == "GET" and path == "/index/events/run_test":
        return [{"event": "index_complete"}]
    if method == "POST" and path == "/ask":
        return [
            {"event": "citations", "chips": [{"chip_type": "document", "anchor": "file_a#block1/b1"}]},
            {"event": "done"},
        ]
    if method == "POST" and path == "/quiz/start":
        return [{"event": "question", "attempt_id": "attempt", "source_anchor": "file_a#block1/b1"}]
    if method == "POST" and path == "/quiz/answer":
        return [{"event": "graded"}, {"event": "quiz_done"}]
    raise AssertionError((method, path))
