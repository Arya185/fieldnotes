#!/usr/bin/env python3
"""Portable Phase 0 verification for Fieldnotes runtime configuration."""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from fastapi.testclient import TestClient

from backend.agent.llm import LLMClient, ResponsesAPIProbeError, verify_responses_api_connection
from backend.config import (
    DEFAULT_OPENAI_MODEL,
    determine_llm_mode,
    env_value,
    load_project_dotenv,
    validate_runtime_configuration,
)
from backend.main import app


class SkippedCheck(RuntimeError):
    """Raised when optional Phase 0 check should be reported as skipped."""


@contextmanager
def temporary_environment(values: dict[str, str | None]):
    original = {key: os.environ.get(key) for key in values}
    try:
        for key, value in values.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield
    finally:
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def check(label: str, action) -> None:
    try:
        action()
    except SkippedCheck as exc:
        message = f" ({exc})" if str(exc) else ""
        print(f"{label:.<30} SKIPPED{message}")
        return
    print(f"{label:.<30} OK")


def verify_configuration() -> None:
    load_project_dotenv()
    with temporary_environment({"FIELDNOTES_USE_FAKE_LLM": "1"}):
        validate_runtime_configuration()


def verify_startup_and_health() -> None:
    with temporary_environment({"FIELDNOTES_USE_FAKE_LLM": "1"}):
        with TestClient(app) as client:
            payload = client.get("/health").json()
    if payload["status"] != "ok" or payload["startup"] != "healthy":
        raise RuntimeError(f"Unexpected health payload: {payload}")


def verify_fake_mode() -> None:
    with temporary_environment({"FIELDNOTES_USE_FAKE_LLM": "1", "OPENAI_API_KEY": None}):
        diagnostics = validate_runtime_configuration()
    if diagnostics.startup_checks["responses_api"] != "ok":
        raise RuntimeError("Fake mode did not disable live Responses API validation")


def verify_live_validation() -> None:
    with temporary_environment({"FIELDNOTES_USE_FAKE_LLM": "0", "OPENAI_API_KEY": None}):
        diagnostics = validate_runtime_configuration()
    if diagnostics.startup_checks["responses_api"] != "ok":
        raise RuntimeError("Missing OPENAI_API_KEY did not fall back to fake mode")
    if determine_llm_mode() != "fake":
        raise RuntimeError("Missing OPENAI_API_KEY did not keep application in fake mode")


def verify_responses_configuration() -> None:
    model = env_value("OPENAI_MODEL", DEFAULT_OPENAI_MODEL).strip()
    if not model:
        raise RuntimeError("OPENAI_MODEL must not be empty")
    with temporary_environment({"FIELDNOTES_USE_FAKE_LLM": "0", "OPENAI_API_KEY": str(uuid4())}):
        diagnostics = validate_runtime_configuration()
        client = LLMClient(model=model)
    if diagnostics.startup_checks["responses_api"] != "configured" or client.model != model:
        raise RuntimeError("Responses API client configuration mismatch")


def verify_live_api() -> None:
    load_project_dotenv()
    api_key = env_value("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise SkippedCheck("OPENAI_API_KEY not set")
    model = env_value("OPENAI_MODEL", DEFAULT_OPENAI_MODEL).strip()
    try:
        probe = verify_responses_api_connection(
            model=model,
            api_key=api_key,
            timeout_seconds=10.0,
        )
    except ResponsesAPIProbeError as exc:
        raise RuntimeError(str(exc)) from exc
    if probe.model != model:
        raise RuntimeError("Live Responses API probe returned unexpected model configuration")


def main() -> int:
    checks = [
        ("[1/7] Configuration", verify_configuration),
        ("[2/7] Startup", verify_startup_and_health),
        ("[3/7] Health", verify_startup_and_health),
        ("[4/7] Fake mode", verify_fake_mode),
        ("[5/7] Live validation", verify_live_validation),
        ("[6/7] Responses config", verify_responses_configuration),
        ("LIVE API", verify_live_api),
    ]
    try:
        for label, action in checks:
            check(label, action)
    except Exception as exc:
        print(f"FAILED: {exc}")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
