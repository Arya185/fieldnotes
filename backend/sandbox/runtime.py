"""Restricted runtime for generated analysis code."""

from __future__ import annotations

import ast
import base64
import csv
import json
import math
import os
import re
import statistics
import time
from collections import Counter, defaultdict, deque
from datetime import date, datetime, time as datetime_time, timedelta, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any


ALLOWED_IMPORT_MODULES = {
    "base64",
    "collections",
    "csv",
    "datetime",
    "json",
    "math",
    "matplotlib",
    "numpy",
    "pandas",
    "re",
    "statistics",
    "time",
    "typing",
}
BLOCKED_NAME_REFERENCES = {
    "__import__",
    "breakpoint",
    "compile",
    "eval",
    "exec",
    "globals",
    "input",
    "locals",
    "open",
    "vars",
}
BLOCKED_CALL_NAMES = BLOCKED_NAME_REFERENCES | {"getattr", "setattr", "delattr"}
ALLOWED_BUILTINS = MappingProxyType(
    {
        "abs": abs,
        "all": all,
        "any": any,
        "bool": bool,
        "dict": dict,
        "enumerate": enumerate,
        "filter": filter,
        "float": float,
        "int": int,
        "isinstance": isinstance,
        "len": len,
        "list": list,
        "map": map,
        "max": max,
        "min": min,
        "print": print,
        "range": range,
        "reversed": reversed,
        "round": round,
        "set": set,
        "sorted": sorted,
        "str": str,
        "sum": sum,
        "tuple": tuple,
        "zip": zip,
    }
)


class SandboxViolation(RuntimeError):
    """Raised when generated code attempts blocked sandbox access."""


def validate_script_source(script_source: str) -> None:
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
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in BLOCKED_CALL_NAMES:
                raise RuntimeError(f"Disallowed call in analysis script: {node.func.id}")
        elif isinstance(node, ast.Name):
            if node.id in BLOCKED_NAME_REFERENCES:
                raise RuntimeError(f"Disallowed name in analysis script: {node.id}")
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("__"):
                raise RuntimeError(f"Disallowed attribute in analysis script: {node.attr}")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if _looks_like_absolute_path(node.value):
                raise RuntimeError(f"Disallowed absolute path in analysis script: {node.value}")


class SandboxPathResolver:
    """Resolve filesystem paths inside workspace jail."""

    def __init__(self, workspace_root: Path, artifacts_dir: Path) -> None:
        self.workspace_root = workspace_root.resolve(strict=True)
        self.artifacts_dir = artifacts_dir.resolve(strict=True)

    def resolve_workspace_path(self, candidate: str | Path) -> Path:
        path = Path(candidate)
        if _looks_like_windows_drive(path.as_posix()) or _looks_like_unc_path(path.as_posix()):
            raise SandboxViolation(f"Path escapes workspace: {candidate}")
        if path.is_absolute():
            joined = path
        else:
            joined = self.workspace_root / path
        try:
            resolved = joined.resolve(strict=False)
        except RuntimeError as exc:
            raise SandboxViolation(f"Path resolution failed: {candidate}") from exc
        self._ensure_within_workspace(resolved)
        return resolved

    def resolve_artifact_path(self, candidate: str | Path) -> Path:
        path = Path(candidate)
        if path.is_absolute():
            raise SandboxViolation(f"Artifact path must be relative: {candidate}")
        resolved = (self.artifacts_dir / path).resolve(strict=False)
        self._ensure_within_directory(resolved, self.artifacts_dir)
        return resolved

    def list_workspace(self) -> list[str]:
        paths: list[str] = []
        for path in sorted(self.workspace_root.rglob("*")):
            resolved = path.resolve(strict=False)
            self._ensure_within_workspace(resolved)
            paths.append(str(resolved.relative_to(self.workspace_root)))
        return paths

    def _ensure_within_workspace(self, resolved: Path) -> None:
        self._ensure_within_directory(resolved, self.workspace_root)

    @staticmethod
    def _ensure_within_directory(resolved: Path, root: Path) -> None:
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise SandboxViolation(f"Path escapes workspace: {resolved}") from exc


class SandboxFiles:
    """Controlled filesystem helpers for generated code."""

    def __init__(self, resolver: SandboxPathResolver, result_path: Path, chart_path: Path) -> None:
        self._resolver = resolver
        self._result_path = result_path
        self._chart_path = chart_path

    def read_text(self, relative_path: str, encoding: str = "utf-8") -> str:
        path = self._resolver.resolve_workspace_path(relative_path)
        return path.read_text(encoding=encoding)

    def read_csv(self, relative_path: str, **kwargs: Any) -> Any:
        path = self._resolver.resolve_workspace_path(relative_path)
        return _load_pandas().read_csv(path, **kwargs)

    def read_json(self, relative_path: str, **kwargs: Any) -> Any:
        path = self._resolver.resolve_workspace_path(relative_path)
        with path.open("r", encoding=kwargs.pop("encoding", "utf-8")) as handle:
            return json.load(handle, **kwargs)

    def list_workspace(self) -> list[str]:
        return self._resolver.list_workspace()

    def write_artifact(self, relative_path: str, contents: str, encoding: str = "utf-8") -> str:
        path = self._resolver.resolve_artifact_path(relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding=encoding)
        return str(path)

    def write_result(self, payload: dict[str, Any]) -> None:
        if not isinstance(payload, dict):
            raise SandboxViolation("Result payload must be dictionary")
        self._result_path.write_text(json.dumps(payload), encoding="utf-8")

    def write_chart_bytes(self, png_bytes: bytes, filename: str | None = None) -> str:
        path = self._chart_path if filename is None else self._resolver.resolve_artifact_path(filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(png_bytes)
        return str(path)

    def chart_path(self) -> str:
        return str(self._chart_path)


class RestrictedImporter:
    """Minimal import gate for generated code."""

    def __init__(self, resolver: SandboxPathResolver, files: SandboxFiles) -> None:
        self._resolver = resolver
        self._files = files
        self._allowed = {
            "collections": __import__("collections"),
            "csv": csv,
            "datetime": __import__("datetime"),
            "base64": base64,
            "json": json,
            "math": math,
            "re": re,
            "statistics": statistics,
            "time": time,
            "typing": __import__("typing"),
        }

    def __call__(self, name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        if level != 0:
            raise SandboxViolation("Relative imports are not allowed")
        top_level = name.split(".", 1)[0]
        if top_level == "numpy":
            return _load_numpy()
        if top_level == "pandas":
            return _patch_pandas_io(self._resolver)
        if top_level == "matplotlib":
            if name == "matplotlib.pyplot":
                return _patch_matplotlib_io(self._files)
            return _load_matplotlib()

        module = self._allowed.get(top_level)
        if module is None:
            raise SandboxViolation(f"Disallowed import in analysis script: {name}")
        return module


def build_execution_globals(
    *,
    workspace_root: Path,
    artifacts_dir: Path,
    result_path: Path,
    chart_path: Path,
) -> dict[str, Any]:
    resolver = SandboxPathResolver(workspace_root, artifacts_dir)
    files = SandboxFiles(resolver, result_path=result_path, chart_path=chart_path)
    pandas_module = LazyModule(lambda: _patch_pandas_io(resolver))
    pyplot_module = LazyModule(lambda: _patch_matplotlib_io(files))
    numpy_module = LazyModule(_load_numpy)

    safe_builtins = dict(ALLOWED_BUILTINS)
    safe_builtins["__import__"] = RestrictedImporter(resolver, files)

    return {
        "__builtins__": safe_builtins,
        "Counter": Counter,
        "base64": base64,
        "date": date,
        "datetime": datetime,
        "defaultdict": defaultdict,
        "deque": deque,
        "files": files,
        "json": json,
        "list_workspace": files.list_workspace,
        "math": math,
        "np": numpy_module,
        "pd": pandas_module,
        "plt": pyplot_module,
        "read_csv": files.read_csv,
        "read_json": files.read_json,
        "read_text": files.read_text,
        "re": re,
        "save_chart": lambda path=None, *args, **kwargs: _patch_matplotlib_io(files).savefig(path, *args, **kwargs),
        "statistics": statistics,
        "time": time,
        "timedelta": timedelta,
        "timezone": timezone,
        "wallclock_time": datetime_time,
        "write_artifact": files.write_artifact,
        "write_chart_bytes": files.write_chart_bytes,
        "write_result": files.write_result,
    }


def execute_script(
    *,
    script_source: str,
    workspace_root: Path,
    artifacts_dir: Path,
    result_path: Path,
    chart_path: Path,
) -> None:
    validate_script_source(script_source)
    sandbox_globals = build_execution_globals(
        workspace_root=workspace_root,
        artifacts_dir=artifacts_dir,
        result_path=result_path,
        chart_path=chart_path,
    )
    compiled = compile(script_source, "<fieldnotes-sandbox>", "exec")
    exec(compiled, sandbox_globals, sandbox_globals)


def _looks_like_absolute_path(value: str) -> bool:
    normalized = value.replace("\\", "/")
    return normalized.startswith("/") or normalized.startswith("~/") or _looks_like_windows_drive(normalized) or _looks_like_unc_path(normalized)


def _looks_like_windows_drive(value: str) -> bool:
    return bool(re.match(r"^[A-Za-z]:[\\/]", value))


def _looks_like_unc_path(value: str) -> bool:
    return value.startswith("//") or value.startswith("\\\\")


class LazyModule:
    def __init__(self, loader) -> None:
        self._loader = loader
        self._module = None

    def _load(self):
        if self._module is None:
            self._module = self._loader()
        return self._module

    def __getattr__(self, item: str):
        return getattr(self._load(), item)


def _load_numpy():
    return __import__("numpy")


def _load_pandas():
    return __import__("pandas")


def _load_matplotlib():
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/fieldnotes-mpl")
    module = __import__("matplotlib")
    module.use("Agg")
    return module


def _load_matplotlib_pyplot():
    _load_matplotlib()
    return __import__("matplotlib.pyplot", fromlist=["pyplot"])


def _patch_pandas_io(resolver: SandboxPathResolver):
    pd = _load_pandas()
    if getattr(pd, "_fieldnotes_sandbox_resolver", None) is resolver:
        return pd

    def _wrap_reader(name: str) -> None:
        original = getattr(pd, name)

        def wrapped(path, *args, **kwargs):
            if isinstance(path, (str, Path)):
                path = resolver.resolve_workspace_path(path)
            return original(path, *args, **kwargs)

        setattr(pd, name, wrapped)

    for reader_name in ("read_csv", "read_excel", "read_json", "read_parquet", "read_table"):
        if hasattr(pd, reader_name):
            _wrap_reader(reader_name)

    for writer_name in ("to_csv", "to_json", "to_excel", "to_pickle", "to_parquet"):
        if hasattr(pd.DataFrame, writer_name):
            original = getattr(pd.DataFrame, writer_name)

            def wrapped(self, path_or_buf=None, *args, _original=original, **kwargs):
                if isinstance(path_or_buf, (str, Path)):
                    path_or_buf = resolver.resolve_artifact_path(path_or_buf)
                    path_or_buf.parent.mkdir(parents=True, exist_ok=True)
                return _original(self, path_or_buf, *args, **kwargs)

            setattr(pd.DataFrame, writer_name, wrapped)

    pd._fieldnotes_sandbox_resolver = resolver
    return pd


def _patch_matplotlib_io(files: SandboxFiles):
    plt = _load_matplotlib_pyplot()
    if getattr(plt, "_fieldnotes_sandbox_patched", False):
        plt._fieldnotes_chart_path = files.chart_path()
        return plt

    original_savefig = plt.savefig

    def wrapped(path=None, *args, **kwargs):
        target = files.chart_path() if path is None else files._resolver.resolve_artifact_path(path)
        Path(target).parent.mkdir(parents=True, exist_ok=True)
        return original_savefig(target, *args, **kwargs)

    plt.savefig = wrapped
    plt._fieldnotes_chart_path = files.chart_path()
    plt._fieldnotes_sandbox_patched = True
    return plt
