#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${1:-${FIELDNOTES_BASE_URL:-}}"
WORKSPACE_PATH="${FIELDNOTES_DEMO_WORKSPACE_PATH:-/app/demo_course}"
QUESTION="${FIELDNOTES_SMOKE_QUESTION:-What does this course say about damping?}"

if [[ -z "${BASE_URL}" ]]; then
  echo "FAIL smoke test: provide the public base URL as the first argument or set FIELDNOTES_BASE_URL" >&2
  exit 2
fi

BASE_URL="${BASE_URL%/}"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

EXPECTED_FILES_JSON='["lab_handout.docx","lab_schedule.csv","lecture_week04_damping.pptx","notes.md","pendulum.csv","pendulum_summary.pdf","problem_set_01.docx","week02_period_and_forces.md","week03_energy_and_damping.md","week05_review.pdf"]'

step() {
  echo
  echo "==> $1"
}

pass() {
  echo "PASS: $1"
}

fail() {
  echo "FAIL: $1" >&2
  exit 1
}

request_json() {
  local method="$1"
  local url="$2"
  local body_file="$3"
  local payload="${4:-}"
  local status

  if [[ -n "${payload}" ]]; then
    status="$(curl -sS -o "${body_file}" -w "%{http_code}" -X "${method}" \
      -H "Content-Type: application/json" \
      --data "${payload}" \
      "${url}")"
  else
    status="$(curl -sS -o "${body_file}" -w "%{http_code}" -X "${method}" "${url}")"
  fi

  echo "${status}"
}

step "Health check"
HEALTH_BODY="${TMP_DIR}/health.json"
HEALTH_STATUS="$(request_json GET "${BASE_URL}/health" "${HEALTH_BODY}")"
[[ "${HEALTH_STATUS}" == "200" ]] || fail "/health returned HTTP ${HEALTH_STATUS}: $(cat "${HEALTH_BODY}")"

python3 - "${HEALTH_BODY}" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if payload.get("status") != "ok":
    raise SystemExit(f"/health payload status was not ok: {payload}")
print(
    "Health details:",
    json.dumps(
        {
            "mode": payload.get("mode"),
            "client": payload.get("client"),
            "provider": payload.get("provider"),
            "model": payload.get("model"),
        },
        sort_keys=True,
    ),
)
PY
pass "/health returned HTTP 200"

step "Start indexing bundled demo workspace"
INDEX_BODY="${TMP_DIR}/index.json"
INDEX_STATUS="$(request_json POST "${BASE_URL}/index" "${INDEX_BODY}" "{\"folder_path\":\"${WORKSPACE_PATH}\"}")"
[[ "${INDEX_STATUS}" == "202" ]] || fail "/index returned HTTP ${INDEX_STATUS}: $(cat "${INDEX_BODY}")"

read -r WORKSPACE_ID EVENTS_PATH <<<"$(python3 - "${INDEX_BODY}" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
workspace_id = payload.get("workspace_id")
events = payload.get("events")
if not workspace_id or not events:
    raise SystemExit(f"/index response missing workspace_id or events: {payload}")
print(workspace_id, events)
PY
)"

INDEX_EVENTS="${TMP_DIR}/index-events.sse"
curl -sS -N "${BASE_URL}${EVENTS_PATH}" > "${INDEX_EVENTS}"

python3 - "${INDEX_EVENTS}" <<'PY'
import json
import sys
from pathlib import Path

events = []
for line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
    if line.startswith("data: "):
        events.append(json.loads(line[6:]))

if not any(event.get("event") == "index_complete" for event in events):
    raise SystemExit(f"index stream missing index_complete: {events}")
if not any(event.get("event") == "brief_ready" for event in events):
    raise SystemExit(f"index stream missing brief_ready: {events}")

index_complete = next(event for event in events if event.get("event") == "index_complete")
print(
    f"Indexed workspace_id={index_complete.get('file_count')} files / {index_complete.get('chunk_count')} chunks"
)
PY
pass "/index completed for ${WORKSPACE_PATH}"

step "Ask one grounded question and verify SSE contract"
ASK_EVENTS="${TMP_DIR}/ask-events.sse"
ASK_STATUS="$(curl -sS -o "${ASK_EVENTS}" -w "%{http_code}" -N \
  -H "Content-Type: application/json" \
  -X POST "${BASE_URL}/ask" \
  --data "{\"workspace_id\":\"${WORKSPACE_ID}\",\"question\":\"${QUESTION}\"}")"
[[ "${ASK_STATUS}" == "200" ]] || fail "/ask returned HTTP ${ASK_STATUS}: $(cat "${ASK_EVENTS}")"

python3 - "${ASK_EVENTS}" "${EXPECTED_FILES_JSON}" <<'PY'
import json
import sys
from pathlib import Path

events = []
for line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
    if line.startswith("data: "):
        events.append(json.loads(line[6:]))

if not events:
    raise SystemExit("/ask returned no SSE data events")

if any(event.get("event") == "error" for event in events):
    raise SystemExit(f"/ask returned error event: {events}")

event_names = [event.get("event") for event in events]
if "intent" not in event_names:
    raise SystemExit(f"/ask stream missing intent event: {event_names}")
if "token" not in event_names:
    raise SystemExit(f"/ask stream missing token event: {event_names}")
if "citations" not in event_names:
    raise SystemExit(f"/ask stream missing citations event: {event_names}")
if "done" not in event_names:
    raise SystemExit(f"/ask stream missing done event: {event_names}")

tokens = [event.get("text", "") for event in events if event.get("event") == "token"]
if not any(token.strip() for token in tokens):
    raise SystemExit("/ask emitted token events but all token text was empty")

expected_files = set(json.loads(sys.argv[2]))
citations_event = next(event for event in events if event.get("event") == "citations")
document_chips = [chip for chip in citations_event.get("chips", []) if chip.get("chip_type") == "document"]
if not document_chips:
    raise SystemExit(f"/ask citations event had no document chips: {citations_event}")

matching_chip = None
for chip in document_chips:
    label = chip.get("label", "")
    if any(name in label for name in expected_files):
        matching_chip = chip
        break

if matching_chip is None:
    raise SystemExit(
        f"/ask citations did not reference a known demo_course file. Chips={document_chips}"
    )

intent_event = next(event for event in events if event.get("event") == "intent")
print(
    json.dumps(
        {
            "intent": intent_event.get("intent"),
            "token_events": len(tokens),
            "citation_label": matching_chip.get("label"),
            "citation_anchor": matching_chip.get("anchor"),
        },
        sort_keys=True,
    )
)
PY
pass "/ask SSE included intent, token, and demo_course citations"

echo
echo "ALL CHECKS PASSED"
