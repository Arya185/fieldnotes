#!/usr/bin/env bash
# Legacy Unix wrapper for the portable Phase 0 verifier.
set -euo pipefail

cd "$(dirname "$0")/.."
exec "${PYTHON:-python3}" scripts/exit_phase0.py
