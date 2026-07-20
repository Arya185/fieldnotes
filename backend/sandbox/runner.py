"""Run generated analysis code in local subprocess sandbox."""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from backend.sandbox.containment import (
    SandboxLimitExceeded,
    SandboxPolicy,
    run_platform_sandbox,
)
from backend.sandbox.environment import build_sandbox_environment
from backend.sandbox.runtime import validate_script_source
from backend.telemetry.tracing import metrics_registry, trace_collector

try:  # pragma: no cover - platform-dependent import
    import resource
except ImportError:  # pragma: no cover - Windows
    resource = None


DEFAULT_TIMEOUT_SECONDS = 15
DEFAULT_MEMORY_BYTES = 512 * 1024 * 1024
DEFAULT_STDIO_BYTES = 1024 * 1024
RUNTIME_RUNNER_PATH = Path(__file__).with_name("runtime_runner.py").resolve()


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
            validate_script_source(script_source)
        except Exception:
            _cleanup_failed_outputs(script_path, result_path, chart_path)
            raise

        environment = build_sandbox_environment(
            workspace_root=workspace_root,
            artifacts_dir=artifacts_dir,
            script_path=script_path,
            result_path=result_path,
            chart_path=chart_path,
        )
        policy = SandboxPolicy(
            timeout_seconds=timeout_seconds,
            memory_bytes=DEFAULT_MEMORY_BYTES,
            max_processes=1,
            max_stdio_bytes=DEFAULT_STDIO_BYTES,
        )

        try:
            completed = run_platform_sandbox(
                command=[sys.executable, "-I", str(RUNTIME_RUNNER_PATH)],
                cwd=workspace_root,
                env=environment,
                policy=policy,
                preexec_fn=(lambda: _limit_resources(policy)) if resource is not None and os.name != "nt" else None,
            )
        except SandboxLimitExceeded as exc:
            _cleanup_failed_outputs(script_path, result_path, chart_path)
            raise RuntimeError(str(exc)) from exc
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


def _cleanup_failed_outputs(*paths: Path) -> None:
    for path in paths:
        path.unlink(missing_ok=True)


def _limit_resources(policy: SandboxPolicy) -> None:
    if resource is None:
        return
    try:
        cpu_budget = max(policy.timeout_seconds + 1, 2)
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_budget, cpu_budget))
        resource.setrlimit(resource.RLIMIT_AS, (policy.memory_bytes, policy.memory_bytes))
        if hasattr(resource, "RLIMIT_NPROC"):
            resource.setrlimit(resource.RLIMIT_NPROC, (policy.max_processes, policy.max_processes))
        if hasattr(resource, "RLIMIT_NOFILE"):
            resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))
    except Exception:
        return
