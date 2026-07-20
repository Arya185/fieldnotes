# Sandbox Demo

This page shows real sandbox enforcement output from `backend/sandbox/runtime.py`, not invented examples.

## Example 1: blocked builtin

Unsafe script:

```python
open("/etc/passwd").read()
write_result({"summary": "bad", "metrics": {}})
```

Actual `validate_script_source()` result:

```text
RuntimeError: Disallowed call in analysis script: open
```

## Example 2: blocked import

Unsafe script:

```python
import os
write_result({"summary": str(os.listdir("/")), "metrics": {}})
```

Actual `validate_script_source()` result:

```text
RuntimeError: Disallowed import in analysis script: os
```

Reproduce locally:

```bash
.venv312/bin/python - <<'PY'
from backend.sandbox.runtime import validate_script_source
validate_script_source('open("/etc/passwd").read()')
PY
```
