"""Test suite package init.

`unittest discover` imports this before any test module in the package, so
this is the one place that can set process-wide defaults before
`backend.main` (and the rate limiter / migration cache it pulls in) gets
imported by the first test file. See backend/auth/security.py
`enforce_rate_limit` for why rate limiting needs a global opt-out here:
it is process-global shared state with no per-test isolation, and the full
suite runs in one process.
"""

from __future__ import annotations

import os

os.environ.setdefault("FIELDNOTES_RATE_LIMIT_DISABLED", "1")
