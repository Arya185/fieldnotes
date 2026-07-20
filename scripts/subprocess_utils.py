"""Portable command construction for project automation scripts."""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable


def npm_executable(
    *,
    platform: str | None = None,
    which: Callable[[str], str | None] = shutil.which,
) -> str:
    """Return npm executable name, with an actionable error when unavailable."""
    is_windows = (platform or os.name) == "nt"
    executable = "npm.cmd" if is_windows else "npm"
    if which(executable) is None:
        raise RuntimeError(
            f"Required Node.js package manager '{executable}' is unavailable on PATH. "
            "Install Node.js (including npm) and retry."
        )
    return executable


def npm_command(
    *arguments: str,
    platform: str | None = None,
    which: Callable[[str], str | None] = shutil.which,
) -> list[str]:
    """Build a shell-free npm command that works on supported platforms."""
    return [npm_executable(platform=platform, which=which), *arguments]
