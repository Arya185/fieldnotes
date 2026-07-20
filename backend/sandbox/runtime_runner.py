"""Entrypoint for restricted sandbox subprocess."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def main() -> int:
    from backend.sandbox.runtime import SandboxViolation, execute_script

    try:
        workspace_root = Path(os.environ["FIELDNOTES_WORKSPACE_ROOT"])
        artifacts_dir = Path(os.environ["FIELDNOTES_ARTIFACTS_DIR"])
        script_path = Path(os.environ["FIELDNOTES_SCRIPT_PATH"])
        result_path = Path(os.environ["FIELDNOTES_RESULT_PATH"])
        chart_path = Path(os.environ["FIELDNOTES_CHART_PATH"])
        script_source = script_path.read_text(encoding="utf-8")
        execute_script(
            script_source=script_source,
            workspace_root=workspace_root,
            artifacts_dir=artifacts_dir,
            result_path=result_path,
            chart_path=chart_path,
        )
        return 0
    except SandboxViolation as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
