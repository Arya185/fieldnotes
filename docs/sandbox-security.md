# Sandbox Security

## Browser Request Boundary

Sandboxing is not only safety boundary. Backend also rejects browser-originated state-changing requests on sensitive routes and configures FastAPI CORS with no allowed origins. This prevents unrelated webpages in same browser from firing cross-origin mutation requests against running local instance. `localhost` binding alone is not treated as sufficient protection.

Fieldnotes executes generated analysis code through `backend/sandbox/runner.py` and `backend/sandbox/runtime.py`.

## Guarantees

- Generated code runs in separate Python subprocess, never in backend process.
- Every filesystem path resolves through one jail rooted at active workspace.
- Absolute paths, `..` traversal, home paths, Windows drive paths, UNC paths, and symlinks escaping workspace are rejected.
- Generated writes are limited to workspace artifact directory: `.fieldnotes/artifacts/`.
- Result payload writes go through `write_result(...)`.
- Chart writes go through `save_chart(...)` or `write_chart_bytes(...)`.
- Network, subprocess, shell, dynamic-import, and unrestricted builtin access are blocked by import policy and restricted globals.
- Wall-clock timeout is enforced on every platform.
- CPU time and memory limits are enforced through OS-native controls on every platform.
- Orphan subprocesses are cleaned up when containment trips.

## Allowed Modules

- `base64`
- `collections`
- `csv`
- `datetime`
- `json`
- `math`
- `matplotlib.pyplot`
- `numpy`
- `pandas`
- `re`
- `statistics`
- `typing`

## Forbidden Modules

Blocked by default unless runtime code itself uses them internally:

- `os`
- `pathlib`
- `subprocess`
- `socket`
- `asyncio`
- `threading`
- `multiprocessing`
- `ctypes`
- `signal`
- `inspect`
- `importlib`
- `pickle`
- `shelve`
- `sqlite3`
- `shutil`
- `tempfile`
- `glob`

## Restricted Builtins

Generated code does not receive unrestricted `open`, `eval`, `exec`, `compile`, `input`, `breakpoint`, `globals`, `locals`, `vars`, `getattr`, `setattr`, or `delattr`.

Available file helpers:

- `read_text(relative_path)`
- `read_csv(relative_path, **kwargs)`
- `read_json(relative_path, **kwargs)`
- `list_workspace()`
- `write_artifact(relative_path, contents)`
- `write_result(payload)`
- `write_chart_bytes(png_bytes, filename=None)`
- `save_chart(path=None, ...)`

## Security Model

1. Runner validates source with AST checks before subprocess launch.
2. Runtime re-executes code under restricted globals and restricted `__import__`.
3. `SandboxPathResolver` canonicalizes paths with `Path.resolve(strict=False)`.
4. Resolver enforces containment with `Path.relative_to(...)`, never string-prefix checks.
5. Pandas and matplotlib file entrypoints are wrapped so file arguments still pass through jail.
6. Linux and macOS apply `setrlimit` for CPU, address space, process count, and open-file count.
7. Windows applies Job Object limits for process memory, working set, per-process CPU time, active process count, and kill-on-close cleanup.
8. Windows sandbox output is bounded in parent process so runaway stdout/stderr cannot grow without limit.

## Windows Implementation

- Launches runtime in dedicated subprocess assigned to one Job Object.
- Enforces:
  - wall-clock timeout
  - per-process CPU-time cap
  - per-process memory cap
  - working-set cap
  - active-process limit of `1`
  - kill-on-job-close cleanup
  - bounded stdout/stderr capture
- If limit trips, sandbox returns deterministic failure and removes partial outputs.

## Known Limitations

- This is hardened CPython restriction layer, not full VM or full container sandbox.
- Protection relies on shipped AST gate, restricted builtins, helper API, jailed IO wrappers, and OS resource controls together.
- Optional scientific stack availability still depends on local Python environment.
