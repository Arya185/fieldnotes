#!/usr/bin/env python3
"""Phase 1 exit verification for Phase 1 release readiness."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from fastapi.testclient import TestClient

from backend.indexer.workspace_manager import WorkspaceManager, workspace_manager
from backend.main import app
from tests.test_api_integration import FakeLLMClient, build_csv_workspace, parse_sse_payloads


def check(label: str, condition: bool) -> None:
    if not condition:
        raise RuntimeError(label)
    print(label)


def main() -> None:
    client = TestClient(app)
    with tempfile.TemporaryDirectory() as temp_dir:
        workspace = Path(temp_dir) / "demo_course"
        build_csv_workspace(workspace)
        with patch("backend.main.llm_client", new=FakeLLMClient()):
            index_response = client.post("/index", json={"folder_path": str(workspace)})
            accepted = index_response.json()
            index_events = parse_sse_payloads(client.get(accepted["events"]).text)
            check("[1/10] OK workspace registry created", workspace_manager.registry_path.exists())
            check("[2/10] OK indexing events complete", [event["event"] for event in index_events][-2:] == ["index_complete", "brief_ready"])

            db_path = workspace / ".fieldnotes" / "fieldnotes.db"
            check("[3/10] OK sqlite initialized", db_path.exists())
            workspace_metadata = workspace / ".fieldnotes" / "workspace.json"
            check("[4/10] OK registry contains workspace_id", workspace_metadata.exists())

            ask_response = client.post(
                "/ask",
                json={"workspace_id": accepted["workspace_id"], "question": "Why does Trial 4 look different?"},
            )
            ask_events = parse_sse_payloads(ask_response.text)
            ask_names = [event["event"] for event in ask_events]
            check("[5/10] OK ask stream contract", ask_names[-1] == "done" and "citations" in ask_names and "artifact" in ask_names)

            citation_event = next(event for event in ask_events if event["event"] == "citations")
            document_chips = [chip for chip in citation_event["chips"] if chip["chip_type"] == "document"]
            code_chips = [chip for chip in citation_event["chips"] if chip["chip_type"] == "code"]
            check("[6/10] OK retrieval and citation integrity", bool(document_chips) and bool(code_chips))

            quiz_response = client.post(
                "/quiz",
                json={"workspace_id": accepted["workspace_id"], "concept_ids": ["grounding"]},
            )
            quiz_events = parse_sse_payloads(quiz_response.text)
            question = next(event for event in quiz_events if event["event"] == "question")
            grade_response = client.post(
                "/quiz/answer",
                json={
                    "workspace_id": accepted["workspace_id"],
                    "attempt_id": question["attempt_id"],
                    "chosen_index": 0,
                },
            )
            grade_events = parse_sse_payloads(grade_response.text)
            check("[7/10] OK quiz flow", [event["event"] for event in grade_events] == ["graded", "quiz_done"])

            notebook = client.get("/notebook", params={"workspace_id": accepted["workspace_id"]}).json()
            check("[8/10] OK notebook persists artifacts", len(notebook["artifacts"]) >= 3)

            artifact_id = grade_events[-1]["artifact_id"]
            artifact_response = client.get(
                f"/artifact/{artifact_id}",
                params={"workspace_id": accepted["workspace_id"]},
            )
            check("[9/10] OK artifact reopen", artifact_response.status_code == 200)

            file_id, locator = question["source_anchor"].split("#", 1)
            source_response = client.get(
                f"/source/{file_id}/{locator}",
                params={"workspace_id": accepted["workspace_id"]},
            )
            check("[10/10] OK source reopening", source_response.status_code == 200 and bool(source_response.json()["text"]))

            workspace_manager._cache.clear()
            check("PASS", workspace_metadata.exists())


if __name__ == "__main__":
    main()
