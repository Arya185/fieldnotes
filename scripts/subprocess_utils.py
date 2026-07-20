"""Portable command construction for project automation scripts."""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable
from pathlib import Path


NPM_EXECUTABLE_NAMES = ("npm", "npm.cmd")
NPX_EXECUTABLE_NAMES = ("npx", "npx.cmd")


def npm_executable(
    *,
    platform: str | None = None,
    which: Callable[[str], str | None] = shutil.which,
) -> str:
    """Return resolved npm executable path, with actionable diagnostics when unavailable."""
    is_windows = (platform or os.name) == "nt"
    preferred_names = ("npm.cmd", "npm") if is_windows else ("npm", "npm.cmd")
    searched_names = (*preferred_names, *NPX_EXECUTABLE_NAMES)
    resolved = {name: which(name) for name in searched_names}
    for name in preferred_names:
        if resolved[name] is not None:
            return resolved[name]

    raise RuntimeError(
        "npm executable unavailable. "
        f"Searched executable names: {', '.join(searched_names)}. "
        f"Current PATH: {os.environ.get('PATH', '')}. "
        f"Current working directory: {Path.cwd()}. "
        f"Python executable: {os.sys.executable}."
    )


def npm_command(
    *arguments: str,
    platform: str | None = None,
    which: Callable[[str], str | None] = shutil.which,
) -> list[str]:
    """Build a shell-free npm command that works on supported platforms."""
    return [npm_executable(platform=platform, which=which), *arguments]
