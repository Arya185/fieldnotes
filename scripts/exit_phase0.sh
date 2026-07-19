#!/usr/bin/env bash
# Phase 0 exit test (implementation-phases.md): a script call to GPT-5.6
# returns a valid structured output against the intent schema (schemas.md §3.1).
set -euo pipefail

cd "$(dirname "$0")/.."

if [ -z "${OPENAI_API_KEY:-}" ]; then
  echo "OPENAI_API_KEY is not set. export it (see .env.example) and re-run." >&2
  exit 1
fi

python scripts/verify_gpt56_api.py