#!/usr/bin/env python3
"""Release-candidate verification for Fieldnotes beta."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.subprocess_utils import npm_command

BACKEND_PORT = 8765
RELEASE_ARTIFACTS_DIR = ROOT_DIR / "scripts" / "release_artifacts"


def expected_version() -> str:
    from backend.config import FIELDNOTES_VERSION

    return FIELDNOTES_VERSION


def build_demo_workspace(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "notes.md").write_text(
        "# Beta release notes\n\n"
        "Fieldnotes grounds answers in local course material.\n\n"
        "Trial 4 shows clear damping anomaly for investigation.\n",
        encoding="utf-8",
    )
    (root / "pendulum.csv").write_text(
        "trial,time,amplitude\n"
        "1,0,10\n1,1,9.2\n1,2,8.5\n"
        "2,0,10\n2,1,9.0\n2,2,8.1\n"
        "3,0,10\n3,1,8.9\n3,2,8.0\n"
        "4,0,10\n4,1,5.4\n4,2,4.0\n",
        encoding="utf-8",
    )
    (root / "pendulum_summary.pdf").write_text(
        "%PDF-1.4\n"
        "1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj\n"
        "2 0 obj<< /Type /Pages /Count 1 /Kids [3 0 R] >>endobj\n"
        "3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 144] /Contents 4 0 R /Resources<< /Font<< /F1 5 0 R >> >> >>endobj\n"
        "4 0 obj<< /Length 81 >>stream\n"
        "BT /F1 12 Tf 36 96 Td (Pendulum summary: Trial 4 damping changes faster than others.) Tj ET\n"
        "endstream endobj\n"
        "5 0 obj<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>endobj\n"
        "xref\n0 6\n0000000000 65535 f \n0000000010 00000 n \n0000000059 00000 n \n0000000116 00000 n \n0000000242 00000 n \n0000000374 00000 n \n"
        "trailer<< /Root 1 0 R /Size 6 >>\nstartxref\n444\n%%EOF\n",
        encoding="utf-8",
    )


def main() -> int:
    RELEASE_ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    results: list[tuple[str, bool, str]] = []
    backend_process: subprocess.Popen[str] | None = None
    base_url = f"http://127.0.0.1:{BACKEND_PORT}"

    try:
        env = os.environ.copy()
        use_fake_mode = env.get("FIELDNOTES_USE_FAKE_LLM", "0") == "1" or not env.get("OPENAI_API_KEY")
        if use_fake_mode:
            env.setdefault("OPENAI_API_KEY", "release-check-key")
            env["FIELDNOTES_USE_FAKE_LLM"] = "1"
        else:
            env["FIELDNOTES_USE_FAKE_LLM"] = "0"

        backend_process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "backend.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(BACKEND_PORT),
            ],
            cwd=ROOT_DIR,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        health_payload = _wait_for_backend_http(backend_process, base_url)
        results.append(("backend starts", True, "uvicorn healthy"))
        if health_payload != {
            "status": "ok",
            "version": expected_version(),
            "mode": "fake" if use_fake_mode else "live",
            "startup": "healthy",
        }:
            raise RuntimeError(f"/health payload mismatch: {health_payload}")
        results.append(("health endpoint responds", True, health_payload["version"]))

        frontend_build = subprocess.run(
            npm_command("run", "build"),
            cwd=ROOT_DIR / "frontend",
            capture_output=True,
            text=True,
            check=False,
        )
        if frontend_build.returncode != 0:
            raise RuntimeError(frontend_build.stderr.strip() or frontend_build.stdout.strip())
        results.append(("frontend builds", True, "vite build passed"))

        frontend_package = json.loads((ROOT_DIR / "frontend" / "package.json").read_text(encoding="utf-8"))
        frontend_version = frontend_package["version"]
        openapi_payload = _request_json(base_url, "GET", "/openapi.json")
        openapi_version = openapi_payload["body"]["info"]["version"]
        if expected_version() != frontend_version or expected_version() != openapi_version:
            raise RuntimeError(
                "Version mismatch: "
                f"backend={expected_version()} frontend={frontend_version} openapi={openapi_version}"
            )
        results.append(("version consistency", True, expected_version()))

        docs_examples = [
            ("README.md", "python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000"),
            ("docs/quickstart.md", "npm run build"),
            ("docs/installation.md", "python -m pip install -r backend/requirements.txt"),
        ]
        for doc_name, expected_text in docs_examples:
            content = (ROOT_DIR / doc_name).read_text(encoding="utf-8")
            if expected_text not in content:
                raise RuntimeError(f"{doc_name} missing expected command: {expected_text}")
        results.append(("documentation example commands", True, "README + installation + quickstart"))

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "release_demo"
            build_demo_workspace(workspace)

            accepted = _request_json(base_url, "POST", "/index", {"folder_path": str(workspace)})["body"]
            events = _request_sse(base_url, "GET", accepted["events"])
            if not any(event["event"] == "index_complete" for event in events):
                raise RuntimeError("index_complete event missing")
            results.append(("workspace indexing succeeds", True, f"workspace_id={accepted['workspace_id']}"))

            ask_events = _request_sse(
                base_url,
                "POST",
                "/ask",
                {
                    "workspace_id": accepted["workspace_id"],
                    "question": "Why does Trial 4 look different?",
                },
            )
            if not any(event["event"] == "done" for event in ask_events):
                raise RuntimeError("ask stream missing done event")
            citations = next(event for event in ask_events if event["event"] == "citations")
            document_chip = next(chip for chip in citations["chips"] if chip["chip_type"] == "document")
            results.append(("chat request succeeds", True, document_chip["anchor"]))

            quiz_start = _request_sse(
                base_url,
                "POST",
                "/quiz/start",
                {
                    "workspace_id": accepted["workspace_id"],
                    "concept_ids": ["grounding"],
                },
            )
            question = next(event for event in quiz_start if event["event"] == "question")
            quiz_end = _request_sse(
                base_url,
                "POST",
                "/quiz/answer",
                {
                    "workspace_id": accepted["workspace_id"],
                    "attempt_id": question["attempt_id"],
                    "chosen_index": 0,
                },
            )
            if [event["event"] for event in quiz_end] != ["graded", "quiz_done"]:
                raise RuntimeError("quiz flow returned wrong event sequence")
            results.append(("quiz flow succeeds", True, question["source_anchor"]))

            notebook = _request_json(
                base_url,
                "GET",
                "/notebook",
                params={"workspace_id": accepted["workspace_id"]},
            )["body"]
            if not notebook["artifacts"]:
                raise RuntimeError("notebook returned no artifacts")
            results.append(("notebook loads", True, f"artifacts={len(notebook['artifacts'])}"))

            anchor = document_chip["anchor"].split("#", 1)[1]
            file_id = document_chip["anchor"].split("#", 1)[0]
            source = _request_json(
                base_url,
                "GET",
                f"/source/{file_id}/{anchor}",
                params={"workspace_id": accepted["workspace_id"]},
            )["body"]
            if not source["text"]:
                raise RuntimeError("source viewer returned empty text")
            results.append(("source viewer opens", True, source["label"]))

        benchmark_run = subprocess.run(
            [sys.executable, str(ROOT_DIR / "scripts" / "run_benchmarks.py")],
            cwd=ROOT_DIR,
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )
        if benchmark_run.returncode != 0:
            raise RuntimeError(benchmark_run.stderr.strip() or benchmark_run.stdout.strip())
        results.append(("benchmark runner executes", True, "scripts/release_artifacts/release_benchmarks.json"))
    except Exception as exc:
        results.append(("release verification", False, str(exc)))
    finally:
        if backend_process is not None:
            _terminate_backend_process(backend_process)

    summary_path = RELEASE_ARTIFACTS_DIR / "release_check_summary.json"
    summary_path.write_text(
        json.dumps(
            [
                {"check": name, "passed": passed, "detail": detail}
                for name, passed, detail in results
            ],
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    overall_pass = all(passed for _, passed, _ in results)
    for index, (name, passed, detail) in enumerate(results, start=1):
        status = "OK" if passed else "FAIL"
        print(f"[{index}/{len(results)}] {status} {name} :: {detail}")
    print("PASS" if overall_pass else "FAIL")
    return 0 if overall_pass else 1


def _wait_for_backend_process(process: subprocess.Popen[str]) -> None:
    deadline = time.time() + 20
    while time.time() < deadline:
        if process.poll() is None:
            time.sleep(0.5)
            if process.poll() is None:
                return
            break
        time.sleep(0.25)
    stderr = process.stderr.read().strip() if process.stderr is not None else ""
    stdout = process.stdout.read().strip() if process.stdout is not None else ""
    raise RuntimeError(stderr or stdout or "backend did not start")


def _wait_for_backend_http(process: subprocess.Popen[str], base_url: str) -> dict:
    deadline = time.time() + 20
    last_error = "backend did not become healthy"
    while time.time() < deadline:
        if process.poll() is not None:
            break
        try:
            response = _request_json(base_url, "GET", "/health")
            if response["status"] == 200:
                return response["body"]
            last_error = _format_http_failure("/health", response["status"], response["body_text"], response["elapsed_ms"])
        except Exception as exc:
            last_error = str(exc)
        time.sleep(0.5)
    stderr = process.stderr.read().strip() if process.stderr is not None else ""
    stdout = process.stdout.read().strip() if process.stdout is not None else ""
    raise RuntimeError(last_error if not (stderr or stdout) else f"{last_error}; stdout={stdout}; stderr={stderr}")


def _terminate_backend_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


def _request_json(
    base_url: str,
    method: str,
    path: str,
    body: dict | None = None,
    *,
    params: dict[str, str] | None = None,
    timeout: float = 20.0,
) -> dict:
    response = _request_text(base_url, method, path, body, params=params, timeout=timeout)
    try:
        parsed = json.loads(response["body_text"])
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"{path} returned non-JSON response in {response['elapsed_ms']}ms: {response['body_text'][:400]}"
        ) from exc
    if response["status"] >= 400:
        raise RuntimeError(_format_http_failure(path, response["status"], response["body_text"], response["elapsed_ms"]))
    response["body"] = parsed
    return response


def _request_sse(
    base_url: str,
    method: str,
    path: str,
    body: dict | None = None,
    *,
    params: dict[str, str] | None = None,
    timeout: float = 60.0,
) -> list[dict]:
    response = _request_text(base_url, method, path, body, params=params, timeout=timeout)
    if response["status"] >= 400:
        raise RuntimeError(_format_http_failure(path, response["status"], response["body_text"], response["elapsed_ms"]))
    return _parse_sse(response["body_text"])


def _request_text(
    base_url: str,
    method: str,
    path: str,
    body: dict | None = None,
    *,
    params: dict[str, str] | None = None,
    timeout: float = 20.0,
) -> dict:
    query = f"?{urlencode(params)}" if params else ""
    url = f"{base_url}{path}{query}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"accept": "application/json"}
    if data is not None:
        headers["content-type"] = "application/json"
    request = Request(url, data=data, method=method, headers=headers)
    started = time.perf_counter()
    try:
        with urlopen(request, timeout=timeout) as response:
            body_text = response.read().decode("utf-8")
            status = response.status
    except HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")
        status = exc.code
    except URLError as exc:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        raise RuntimeError(f"{path} request failed after {elapsed_ms}ms: {exc.reason}") from exc
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return {
        "status": status,
        "body_text": body_text,
        "elapsed_ms": elapsed_ms,
    }


def _format_http_failure(path: str, status: int, body_text: str, elapsed_ms: int) -> str:
    body = body_text.strip().replace("\n", "\\n")
    return f"{path} failed status={status} elapsed_ms={elapsed_ms} body={body[:400]}"


def _parse_sse(body: str) -> list[dict]:
    payloads: list[dict] = []
    for block in body.split("\n\n"):
        if not block.startswith("data: "):
            continue
        payloads.append(json.loads(block[6:]))
    return payloads


if __name__ == "__main__":
    raise SystemExit(main())
