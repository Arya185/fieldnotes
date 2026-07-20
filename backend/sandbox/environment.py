"""Shared sandbox subprocess environment construction."""

from __future__ import annotations

import os
from pathlib import Path


THREAD_LIMIT_ENV_VARS = (
    "OPENBLAS_NUM_THREADS",
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
)


def build_sandbox_environment(
    *,
    workspace_root: Path,
    artifacts_dir: Path,
    script_path: Path,
    result_path: Path,
    chart_path: Path,
) -> dict[str, str]:
    environment = {
        "PYTHONUNBUFFERED": "1",
        "PYTHONNOUSERSITE": "1",
        "FIELDNOTES_WORKSPACE_ROOT": str(workspace_root.resolve()),
        "FIELDNOTES_ARTIFACTS_DIR": str(artifacts_dir.resolve()),
        "FIELDNOTES_SCRIPT_PATH": str(script_path.resolve()),
        "FIELDNOTES_RESULT_PATH": str(result_path),
        "FIELDNOTES_CHART_PATH": str(chart_path),
        "MPLBACKEND": "Agg",
        "PATH": os.environ.get("PATH", ""),
    }
    for name in THREAD_LIMIT_ENV_VARS:
        environment[name] = os.environ.get(name, "1")
    return environment
