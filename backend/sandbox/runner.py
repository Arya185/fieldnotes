"""Run generated analysis code in local subprocess sandbox."""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from backend.telemetry.tracing import metrics_registry, trace_collector

try:  # pragma: no cover - platform-dependent import
    import resource
except ImportError:  # pragma: no cover - Windows
    resource = None


DEFAULT_TIMEOUT_SECONDS = 15
DEFAULT_MEMORY_BYTES = 512 * 1024 * 1024
ALLOWED_IMPORT_MODULES = {
    "base64",
    "collections",
    "json",
    "math",
    "matplotlib",
    "numpy",
    "os",
    "pandas",
    "pathlib",
    "scipy",
    "statistics",
    "time",
}
DANGEROUS_CALL_NAMES = {"eval", "exec", "compile", "__import__", "input", "open"}
DANGEROUS_ATTRIBUTE_CALLS = {
    ("os", "system"),
    ("os", "popen"),
    ("os", "spawnl"),
    ("os", "spawnlp"),
    ("os", "spawnv"),
    ("os", "spawnvp"),
    ("os", "execv"),
    ("os", "execve"),
    ("os", "execl"),
    ("os", "execlp"),
    ("os", "fork"),
    ("subprocess", "run"),
    ("subprocess", "Popen"),
    ("subprocess", "call"),
    ("subprocess", "check_call"),
    ("subprocess", "check_output"),
    ("socket", "socket"),
}


@dataclass(frozen=True)
class SandboxResult:
    script_path: Path
    result_path: Path
    chart_path: Path
    stdout: str
    stderr: str
    result_payload: dict


def run_generated_analysis(
    *,
    workspace_root: Path,
    artifacts_dir: Path,
    answer_id: str,
    script_source: str,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> SandboxResult:
    """Execute generated analysis against workspace-local files."""

    with trace_collector.span("sandbox", answer_id=answer_id):
        started = time.perf_counter()
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        script_path = artifacts_dir / f"{answer_id}_analysis.py"
        result_path = artifacts_dir / f"{answer_id}_result.json"
        chart_path = artifacts_dir / f"{answer_id}_chart.png"
        script_path.write_text(script_source, encoding="utf-8")
        try:
            _validate_script_source(script_source)
        except Exception:
            _cleanup_failed_outputs(script_path, result_path, chart_path)
            raise

        environment = {
            "PYTHONUNBUFFERED": "1",
            "PYTHONNOUSERSITE": "1",
            "FIELDNOTES_RESULT_PATH": str(result_path),
            "FIELDNOTES_CHART_PATH": str(chart_path),
            "MPLBACKEND": "Agg",
            "PATH": os.environ.get("PATH", ""),
        }

        try:
            subprocess_kwargs = {
                "cwd": workspace_root,
                "env": environment,
                "capture_output": True,
                "text": True,
                "timeout": timeout_seconds,
                "check": False,
            }
            if resource is not None and os.name != "nt":
                subprocess_kwargs["preexec_fn"] = _limit_resources
            completed = subprocess.run(
                [sys.executable, "-I", str(script_path)],
                **subprocess_kwargs,
            )
        except subprocess.TimeoutExpired as exc:
            _cleanup_failed_outputs(script_path, result_path, chart_path)
            raise RuntimeError(f"Analysis sandbox timed out after {timeout_seconds}s") from exc
        metrics_registry.record("sandbox_execution_time_ms", (time.perf_counter() - started) * 1000)
        if completed.returncode != 0:
            _cleanup_failed_outputs(script_path, result_path, chart_path)
            raise RuntimeError(
                f"Analysis sandbox failed with exit code {completed.returncode}: "
                f"{completed.stderr.strip() or completed.stdout.strip()}"
            )
        if not result_path.exists():
            _cleanup_failed_outputs(script_path, result_path, chart_path)
            raise RuntimeError("Analysis sandbox did not produce result payload")

        try:
            result_payload = json.loads(result_path.read_text(encoding="utf-8"))
        except Exception as exc:
            _cleanup_failed_outputs(script_path, result_path, chart_path)
            raise RuntimeError("Analysis sandbox produced invalid result payload") from exc
        return SandboxResult(
            script_path=script_path,
            result_path=result_path,
            chart_path=chart_path,
            stdout=completed.stdout,
            stderr=completed.stderr,
            result_payload=result_payload,
        )


def _validate_script_source(script_source: str) -> None:
    try:
        module = ast.parse(script_source, mode="exec")
    except SyntaxError as exc:
        raise RuntimeError(f"Analysis script is not valid Python: {exc.msg}") from exc

    for node in ast.walk(module):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top_level = alias.name.split(".", 1)[0]
                if top_level not in ALLOWED_IMPORT_MODULES:
                    raise RuntimeError(f"Disallowed import in analysis script: {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if node.module is None:
                raise RuntimeError("Relative imports are not allowed in analysis script")
            top_level = node.module.split(".", 1)[0]
            if top_level not in ALLOWED_IMPORT_MODULES:
                raise RuntimeError(f"Disallowed import in analysis script: {node.module}")
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in DANGEROUS_CALL_NAMES:
                raise RuntimeError(f"Disallowed call in analysis script: {node.func.id}")
            if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
                pair = (node.func.value.id, node.func.attr)
                if pair in DANGEROUS_ATTRIBUTE_CALLS:
                    raise RuntimeError(
                        f"Disallowed call in analysis script: {node.func.value.id}.{node.func.attr}"
                    )


def _cleanup_failed_outputs(*paths: Path) -> None:
    for path in paths:
        path.unlink(missing_ok=True)


def _limit_resources() -> None:
    if resource is None:
        return
    try:
        resource.setrlimit(resource.RLIMIT_CPU, (DEFAULT_TIMEOUT_SECONDS, DEFAULT_TIMEOUT_SECONDS))
        resource.setrlimit(resource.RLIMIT_AS, (DEFAULT_MEMORY_BYTES, DEFAULT_MEMORY_BYTES))
    except Exception:
        return
