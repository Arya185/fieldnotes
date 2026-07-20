"""Platform-native sandbox containment helpers."""

from __future__ import annotations

import os
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path


DEFAULT_STDIO_BYTES = 1024 * 1024


@dataclass(frozen=True)
class SandboxPolicy:
    timeout_seconds: int
    memory_bytes: int
    max_processes: int = 1
    max_stdio_bytes: int = DEFAULT_STDIO_BYTES


@dataclass(frozen=True)
class CompletedSandboxProcess:
    returncode: int
    stdout: str
    stderr: str


class SandboxLimitExceeded(RuntimeError):
    """Raised when sandbox exceeds configured platform limit."""


def run_platform_sandbox(
    *,
    command: list[str],
    cwd: Path,
    env: dict[str, str],
    policy: SandboxPolicy,
    preexec_fn=None,
) -> CompletedSandboxProcess:
    if os.name == "nt":
        return _run_windows_sandbox(command=command, cwd=cwd, env=env, policy=policy)

    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=policy.timeout_seconds,
            check=False,
            preexec_fn=preexec_fn,
        )
    except subprocess.TimeoutExpired as exc:
        raise SandboxLimitExceeded(f"Analysis sandbox timed out after {policy.timeout_seconds}s") from exc
    return CompletedSandboxProcess(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _run_windows_sandbox(
    *,
    command: list[str],
    cwd: Path,
    env: dict[str, str],
    policy: SandboxPolicy,
) -> CompletedSandboxProcess:
    from backend.sandbox.win32_job import WindowsJobObject, WindowsSandboxLimitExceeded

    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        text=False,
        creationflags=creationflags,
    )
    stdout_collector = _OutputCollector(limit_bytes=policy.max_stdio_bytes)
    stderr_collector = _OutputCollector(limit_bytes=policy.max_stdio_bytes)
    stdout_thread = threading.Thread(target=stdout_collector.consume, args=(process.stdout,), daemon=True)
    stderr_thread = threading.Thread(target=stderr_collector.consume, args=(process.stderr,), daemon=True)
    stdout_thread.start()
    stderr_thread.start()

    try:
        with WindowsJobObject(policy=policy, process=process):
            try:
                returncode = process.wait(timeout=policy.timeout_seconds)
            except subprocess.TimeoutExpired as exc:
                _kill_process_tree(process)
                raise SandboxLimitExceeded(f"Analysis sandbox timed out after {policy.timeout_seconds}s") from exc
            stdout_thread.join(timeout=1)
            stderr_thread.join(timeout=1)
            if stdout_collector.limit_exceeded or stderr_collector.limit_exceeded:
                _kill_process_tree(process)
                raise SandboxLimitExceeded(
                    f"Analysis sandbox exceeded stdout/stderr limit of {policy.max_stdio_bytes} bytes"
                )
            return CompletedSandboxProcess(
                returncode=returncode,
                stdout=stdout_collector.text(),
                stderr=stderr_collector.text(),
            )
    except WindowsSandboxLimitExceeded as exc:
        _kill_process_tree(process)
        raise SandboxLimitExceeded(str(exc)) from exc
    finally:
        _close_stream(process.stdout)
        _close_stream(process.stderr)


class _OutputCollector:
    def __init__(self, *, limit_bytes: int) -> None:
        self.limit_bytes = limit_bytes
        self.limit_exceeded = False
        self._buffer = bytearray()

    def consume(self, stream) -> None:
        if stream is None:
            return
        while True:
            chunk = stream.read(4096)
            if not chunk:
                break
            remaining = self.limit_bytes - len(self._buffer)
            if remaining > 0:
                self._buffer.extend(chunk[:remaining])
            if len(self._buffer) >= self.limit_bytes:
                self.limit_exceeded = True
                break

    def text(self) -> str:
        return self._buffer.decode("utf-8", errors="replace")


def _kill_process_tree(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    try:
        process.kill()
    except Exception:
        return
    try:
        process.wait(timeout=5)
    except Exception:
        return


def _close_stream(stream) -> None:
    if stream is None:
        return
    try:
        stream.close()
    except Exception:
        return
