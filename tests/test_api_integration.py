from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("FIELDNOTES_USE_FAKE_LLM", "1")

from fastapi.testclient import TestClient

from backend.db import connect_sqlite
from backend.main import app, get_workspace_manager, get_workspace_record
from backend.indexer.workspace_manager import WorkspaceManager, workspace_manager
from backend.indexer.bm25 import RetrievalChunk
from backend.models import ConceptUpdate, QuizQuestionSchema, RouteIntentSchema
from backend.release import FakeLLMClient as DeterministicFakeLLMClient


class FakeLLMClient:
    def classify_intent(self, question: str) -> RouteIntentSchema:
        if "why" in question.lower() or "trial" in question.lower():
            return RouteIntentSchema(intent="analyze", targets=[], connect=True)
        return RouteIntentSchema(intent="retrieve", targets=[], connect=False)

    def resolve_retrieval(self, question: str, retrieval_provider):
        return retrieval_provider.search(question, limit=5)

    def stream_grounded_answer(
        self,
        question: str,
        intent: str,
        retrieval_results,
        execution_context: str | None = None,
    ):
        yield f"Grounded answer for {question}"

    def generate_quiz_question(self, retrieval_results, concept_ids=None) -> QuizQuestionSchema:
        first = retrieval_results[0]
        return QuizQuestionSchema(
            question="Which file contains the grounded concept?",
            options=["alpha.txt", "beta.txt", "gamma.txt", "delta.txt"],
            correct_index=0,
            concept=(concept_ids or ["grounding"])[0],
            source_anchor=f"{first.file_id}#{first.anchor}",
        )

    def extract_concepts(self, question: str, retrieval_results) -> list[ConceptUpdate]:
        return [
            ConceptUpdate(
                concept_id="concept_grounding",
                name="grounding",
                state="touched",
            )
        ]

    def generate_analysis_script(self, *, question: str, retrieval_results, dataset_profiles_json: str):
        profiles = json.loads(dataset_profiles_json)
        file_path = profiles[0]["file_path"]
        return type(
            "AnalysisScript",
            (),
            {
                "target_file_path": file_path,
                "title": "Trial analysis",
                "needs_chart": True,
                "script": (
                    "import base64\n"
                    "import pandas as pd\n"
                    f"frame = pd.read_csv({file_path!r})\n"
                    "numeric = frame.select_dtypes(include=['number'])\n"
                    "summary = {'rows': int(len(frame)), 'columns': list(frame.columns)}\n"
                    "png_bytes = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO7Z0XQAAAAASUVORK5CYII=')\n"
                    "write_chart_bytes(png_bytes)\n"
                    "write_result({'summary': 'analysis complete', 'metrics': summary})\n"
                    "print('analysis complete')\n"
                ),
            },
        )()


def parse_sse_payloads(response_text: str) -> list[dict]:
    payloads: list[dict] = []
    for block in response_text.split("\n\n"):
        if not block.strip():
            continue
        if not block.startswith("data: "):
            continue
        payloads.append(json.loads(block[6:]))
    return payloads


def build_workspace(root: Path, filename: str, contents: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / filename).write_text(contents, encoding="utf-8")


def build_csv_workspace(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "pendulum.csv").write_text(
        "trial,time,amplitude\n"
        "1,0,10\n1,1,9\n1,2,8\n"
        "2,0,10\n2,1,8.8\n2,2,7.9\n"
        "3,0,10\n3,1,8.9\n3,2,8.1\n"
        "4,0,10\n4,1,5.5\n4,2,4.2\n",
        encoding="utf-8",
    )
    (root / "notes.txt").write_text("Trial 4 damping explanation", encoding="utf-8")


class ApiIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base = Path(self.temp_dir.name)
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_lifespan_initializes_runtime_and_preserves_health_contract(self) -> None:
        with patch.dict(os.environ, {"FIELDNOTES_USE_FAKE_LLM": "1"}, clear=True):
            with TestClient(app) as client:
                response = client.get("/health")
                self.assertEqual(
                    response.json(),
                    {
                        "status": "ok",
                        "version": "1.0.0-beta.1",
                        "mode": "fake",
                        "startup": "healthy",
                    },
                )
                self.assertEqual(app.state.release_metadata["version"], "1.0.0-beta.1")

    def test_lifespan_without_api_key_falls_back_to_fake_mode(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with TestClient(app) as client:
                response = client.get("/health")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["mode"], "fake")
                self.assertEqual(response.json()["startup"], "healthy")

    def test_notebook_invalid_workspace_returns_stable_rest_error(self) -> None:
        response = self.client.get("/notebook", params={"workspace_id": "missing"})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["code"], "WORKSPACE_NOT_FOUND")
        self.assertIn("request_id", response.json())
        self.assertNotIn("detail", response.json())

    def test_get_workspace_record_dependency_raises_404_for_missing_workspace(self) -> None:
        with self.assertRaises(Exception) as context:
            get_workspace_record("missing", manager=workspace_manager)
        self.assertEqual(getattr(context.exception, "status_code", None), 404)
        self.assertEqual(getattr(context.exception, "detail", None), "Unknown workspace_id")

    def test_workspace_manager_dependency_can_be_overridden_in_tests(self) -> None:
        class OverrideWorkspaceManager:
            def get(self, workspace_id: str):
                if workspace_id == "override":
                    return type(
                        "Record",
                        (),
                        {
                            "workspace_id": "override",
                            "root": Path("/tmp/override"),
                            "db_path": Path("/tmp/override/.fieldnotes/fieldnotes.db"),
                            "artifacts_dir": Path("/tmp/override/.fieldnotes/artifacts"),
                            "metadata_path": Path("/tmp/override/.fieldnotes/workspace.json"),
                        },
                    )()
                return None

            def last_recovery_warning(self):
                return "override warning"

        app.dependency_overrides[get_workspace_manager] = lambda: OverrideWorkspaceManager()
        try:
            health = self.client.get("/health")
            self.assertEqual(health.status_code, 200)
            self.assertEqual(health.json()["registry_warning"], "override warning")

            record = get_workspace_record("override", manager=OverrideWorkspaceManager())
            self.assertEqual(record.workspace_id, "override")
        finally:
            app.dependency_overrides.pop(get_workspace_manager, None)

    def test_index_allows_trusted_origin_and_rejects_foreign_origin(self) -> None:
        ws = self.base / "origin-block"
        build_workspace(ws, "alpha.txt", "alpha")

        trusted = self.client.post(
            "/index",
            json={"folder_path": str(ws)},
            headers={"Origin": "http://127.0.0.1:5173"},
        )
        self.assertEqual(trusted.status_code, 202)

        trusted_dynamic_port = self.client.post(
            "/index",
            json={"folder_path": str(ws)},
            headers={
                "Origin": "http://127.0.0.1:5175",
                "Referer": "http://127.0.0.1:5175/#workspace",
            },
        )
        self.assertEqual(trusted_dynamic_port.status_code, 202)

        response = self.client.post(
            "/index",
            json={"folder_path": str(ws)},
            headers={"Origin": "https://evil.example"},
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "INVALID_REQUEST")

    def test_health_includes_registry_warning_when_recovery_occurred(self) -> None:
        with patch.object(workspace_manager, "last_recovery_warning", return_value="Registry file was corrupted and was recreated."):
            response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["registry_warning"], "Registry file was corrupted and was recreated.")

    def test_concurrent_indexing_runs_and_run_isolation(self) -> None:
        ws1 = self.base / "ws1"
        ws2 = self.base / "ws2"
        build_workspace(ws1, "alpha.txt", "alpha unique content")
        build_workspace(ws2, "beta.txt", "beta unique content")

        r1 = self.client.post("/index", json={"folder_path": str(ws1)})
        r2 = self.client.post("/index", json={"folder_path": str(ws2)})
        body1 = r1.json()
        body2 = r2.json()

        self.assertNotEqual(body1["run_id"], body2["run_id"])
        self.assertNotEqual(body1["workspace_id"], body2["workspace_id"])

        e1 = self.client.get(body1["events"])
        e2 = self.client.get(body2["events"])
        payloads1 = parse_sse_payloads(e1.text)
        payloads2 = parse_sse_payloads(e2.text)

        names1 = [payload.get("display_name") for payload in payloads1 if "display_name" in payload]
        names2 = [payload.get("display_name") for payload in payloads2 if "display_name" in payload]
        self.assertIn("alpha.txt", names1)
        self.assertNotIn("beta.txt", names1)
        self.assertIn("beta.txt", names2)
        self.assertNotIn("alpha.txt", names2)

    def test_event_ordering_for_index_run(self) -> None:
        ws = self.base / "order"
        build_workspace(ws, "order.txt", "ordered content")
        response = self.client.post("/index", json={"folder_path": str(ws)})
        payloads = parse_sse_payloads(self.client.get(response.json()["events"]).text)
        event_names = [payload["event"] for payload in payloads]
        self.assertEqual(event_names[-2:], ["index_complete", "brief_ready"])
        self.assertLess(event_names.index("file_started"), event_names.index("file_parsed"))

    def test_empty_workspace_is_indexed_but_not_treated_as_ready_content(self) -> None:
        ws = self.base / "empty-index"
        ws.mkdir(parents=True, exist_ok=True)
        (ws / "image.jpg").write_text("not an indexable file", encoding="utf-8")

        response = self.client.post("/index", json={"folder_path": str(ws)})
        payloads = parse_sse_payloads(self.client.get(response.json()["events"]).text)

        index_complete = next(payload for payload in payloads if payload["event"] == "index_complete")
        self.assertEqual(index_complete["file_count"], 0)
        self.assertEqual(index_complete["chunk_count"], 0)

        notebook = self.client.get("/notebook", params={"workspace_id": response.json()["workspace_id"]})
        self.assertEqual(notebook.status_code, 200)
        self.assertEqual(notebook.json()["file_count"], 0)
        self.assertEqual(notebook.json()["chunk_count"], 0)

        ask = self.client.post(
            "/ask",
            json={"workspace_id": response.json()["workspace_id"], "question": "Summarize this workspace"},
        )
        ask_payloads = parse_sse_payloads(ask.text)
        grounding = next(
            payload
            for payload in ask_payloads
            if payload["event"] == "step" and payload["step"] == "grounding" and payload["status"] != "started"
        )
        retrieval_step = next(
            payload
            for payload in ask_payloads
            if payload["event"] == "step" and payload["step"] == "retrieval" and payload["status"] != "started"
        )
        self.assertEqual(retrieval_step["status"], "no_match")
        self.assertEqual(retrieval_step["label"], "workspace contains no searchable passages")
        self.assertEqual(grounding["status"], "no_match")
        self.assertEqual(grounding["label"], "workspace has no indexed content")

        quiz = self.client.post(
            "/quiz/start",
            json={"workspace_id": response.json()["workspace_id"], "concept_ids": []},
        )
        quiz_payloads = parse_sse_payloads(quiz.text)
        error_event = next(payload for payload in quiz_payloads if payload["event"] == "error")
        self.assertEqual(error_event["code"], "INVALID_REQUEST")
        self.assertIn("no searchable content", error_event["message"].lower())
        self.assertIn("supported file types", error_event["message"].lower())

    def test_reindex_ignores_fieldnotes_internal_state(self) -> None:
        ws = self.base / "reindex"
        build_workspace(ws, "alpha.txt", "alpha unique content")
        first = self.client.post("/index", json={"folder_path": str(ws)}).json()
        self.client.get(first["events"])
        second = self.client.post("/index", json={"folder_path": str(ws)}).json()
        self.client.get(second["events"])

        connection = connect_sqlite(ws / ".fieldnotes" / "fieldnotes.db")
        try:
            paths = [str(row["path"]) for row in connection.execute("SELECT path FROM files ORDER BY path").fetchall()]
        finally:
            connection.close()
        self.assertEqual(paths, ["alpha.txt"])

    @patch("backend.main.llm_client", new_callable=lambda: FakeLLMClient())
    def test_ask_against_multiple_workspaces_uses_selected_workspace_only(self, _fake_llm) -> None:
        ws1 = self.base / "ask1"
        ws2 = self.base / "ask2"
        build_workspace(ws1, "alpha.txt", "alpha topic only")
        build_workspace(ws2, "beta.txt", "beta topic only")

        index1 = self.client.post("/index", json={"folder_path": str(ws1)}).json()
        index2 = self.client.post("/index", json={"folder_path": str(ws2)}).json()
        self.client.get(index1["events"])
        self.client.get(index2["events"])

        ask1 = self.client.post(
            "/ask",
            json={"workspace_id": index1["workspace_id"], "question": "alpha"},
        )
        ask2 = self.client.post(
            "/ask",
            json={"workspace_id": index2["workspace_id"], "question": "beta"},
        )

        payloads1 = parse_sse_payloads(ask1.text)
        payloads2 = parse_sse_payloads(ask2.text)

        citations1 = next(payload for payload in payloads1 if payload["event"] == "citations")
        citations2 = next(payload for payload in payloads2 if payload["event"] == "citations")
        labels1 = [chip["label"] for chip in citations1["chips"]]
        labels2 = [chip["label"] for chip in citations2["chips"]]
        self.assertTrue(any("alpha.txt" in label for label in labels1))
        self.assertFalse(any("beta.txt" in label for label in labels1))
        self.assertTrue(any("beta.txt" in label for label in labels2))
        self.assertFalse(any("alpha.txt" in label for label in labels2))

    @patch("backend.main.llm_client", new_callable=lambda: FakeLLMClient())
    def test_ask_grounding_step_reports_ok_when_retrieval_has_results(self, _fake_llm) -> None:
        ws = self.base / "ask-grounded"
        build_workspace(ws, "alpha.txt", "alpha topic only")
        index = self.client.post("/index", json={"folder_path": str(ws)}).json()
        self.client.get(index["events"])

        ask = self.client.post(
            "/ask",
            json={"workspace_id": index["workspace_id"], "question": "alpha"},
        )
        payloads = parse_sse_payloads(ask.text)
        grounding = next(
            payload
            for payload in payloads
            if payload["event"] == "step" and payload["step"] == "grounding" and payload["status"] != "started"
        )
        self.assertEqual(grounding["status"], "ok")
        self.assertEqual(grounding["label"], "answer grounded")

    def test_ask_grounding_step_reports_no_match_when_retrieval_is_empty(self) -> None:
        class EmptyRetrievalLLM(FakeLLMClient):
            def resolve_retrieval(self, question: str, retrieval_provider):
                return []

        ws = self.base / "ask-no-match"
        build_workspace(ws, "alpha.txt", "alpha topic only")
        index = self.client.post("/index", json={"folder_path": str(ws)}).json()
        self.client.get(index["events"])

        with patch("backend.main.llm_client", new=EmptyRetrievalLLM()):
            ask = self.client.post(
                "/ask",
                json={"workspace_id": index["workspace_id"], "question": "missing topic"},
            )

        payloads = parse_sse_payloads(ask.text)
        grounding = next(
            payload
            for payload in payloads
            if payload["event"] == "step" and payload["step"] == "grounding" and payload["status"] != "started"
        )
        citations = next(payload for payload in payloads if payload["event"] == "citations")
        self.assertEqual(grounding["status"], "no_match")
        self.assertEqual(grounding["label"], "no supporting sources found")
        self.assertEqual(citations["chips"], [])
        self.assertFalse(any(payload["event"] == "concepts" for payload in payloads))

    def test_ask_emits_no_concepts_and_persists_none_when_retrieval_is_empty(self) -> None:
        class EmptyRetrievalLLM(FakeLLMClient):
            def resolve_retrieval(self, question: str, retrieval_provider):
                return []

        ws = self.base / "ask-no-concepts"
        build_workspace(ws, "alpha.txt", "alpha topic only")
        index = self.client.post("/index", json={"folder_path": str(ws)}).json()
        self.client.get(index["events"])

        with patch("backend.main.llm_client", new=EmptyRetrievalLLM()):
            ask = self.client.post(
                "/ask",
                json={"workspace_id": index["workspace_id"], "question": "missing topic"},
            )

        payloads = parse_sse_payloads(ask.text)
        self.assertFalse(any(payload["event"] == "concepts" for payload in payloads))

        connection = connect_sqlite(ws / ".fieldnotes" / "fieldnotes.db")
        try:
            concept_count = connection.execute("SELECT COUNT(*) AS count FROM concepts").fetchone()["count"]
        finally:
            connection.close()
        self.assertEqual(concept_count, 0)

    @patch("backend.main.llm_client", new_callable=lambda: FakeLLMClient())
    def test_ask_does_not_ground_nonsense_query_on_vector_only_collision(self, _fake_llm) -> None:
        ws = self.base / "ask-nonsense"
        build_workspace(ws, "alpha.txt", "pendulum damping ratio and oscillation notes")
        index = self.client.post("/index", json={"folder_path": str(ws)}).json()
        self.client.get(index["events"])

        ask = self.client.post(
            "/ask",
            json={"workspace_id": index["workspace_id"], "question": "zebra quantum banana content"},
        )
        payloads = parse_sse_payloads(ask.text)
        grounding = next(
            payload
            for payload in payloads
            if payload["event"] == "step" and payload["step"] == "grounding" and payload["status"] != "started"
        )
        citations = next(payload for payload in payloads if payload["event"] == "citations")
        self.assertEqual(grounding["status"], "no_match")
        self.assertEqual(grounding["label"], "no supporting sources found")
        self.assertEqual(citations["chips"], [])
        self.assertFalse(any(payload["event"] == "concepts" for payload in payloads))

    @patch("backend.main.llm_client", new_callable=lambda: FakeLLMClient())
    def test_ask_event_sequence_contains_required_events(self, _fake_llm) -> None:
        ws = self.base / "ask-seq"
        build_csv_workspace(ws)
        index = self.client.post("/index", json={"folder_path": str(ws)}).json()
        self.client.get(index["events"])

        ask = self.client.post(
            "/ask",
            json={"workspace_id": index["workspace_id"], "question": "Why does Trial 4 look different?"},
        )
        payloads = parse_sse_payloads(ask.text)
        events = [payload["event"] for payload in payloads]
        self.assertIn("intent", events)
        self.assertIn("step", events)
        self.assertIn("token", events)
        self.assertIn("artifact", events)
        self.assertIn("citations", events)
        self.assertIn("concepts", events)
        self.assertEqual(events[-1], "done")
        step_types = [payload["step"] for payload in payloads if payload["event"] == "step"]
        self.assertIn("codegen", step_types)
        self.assertIn("execution", step_types)

    @patch("backend.main.llm_client", new_callable=lambda: FakeLLMClient())
    def test_ask_persists_explainer_artifact(self, _fake_llm) -> None:
        ws = self.base / "artifact-ask"
        build_csv_workspace(ws)
        index = self.client.post("/index", json={"folder_path": str(ws)}).json()
        self.client.get(index["events"])

        ask = self.client.post(
            "/ask",
            json={"workspace_id": index["workspace_id"], "question": "Why does Trial 4 look different?"},
        )
        payloads = parse_sse_payloads(ask.text)
        artifact_events = [payload for payload in payloads if payload["event"] == "artifact"]
        self.assertGreaterEqual(len(artifact_events), 2)
        self.assertTrue(any(event["kind"] == "script" for event in artifact_events))
        self.assertTrue(any(event["kind"] == "explainer" for event in artifact_events))

        notebook = self.client.get("/notebook", params={"workspace_id": index["workspace_id"]})
        artifacts = notebook.json()["artifacts"]
        artifact_ids = {event["artifact_id"] for event in artifact_events}
        self.assertTrue(any(artifact["id"] in artifact_ids for artifact in artifacts))

    @patch("backend.main.llm_client", new_callable=lambda: FakeLLMClient())
    def test_quiz_artifact_persistence_and_citation_integrity(self, _fake_llm) -> None:
        ws = self.base / "quiz"
        build_csv_workspace(ws)
        index = self.client.post("/index", json={"folder_path": str(ws)}).json()
        self.client.get(index["events"])

        quiz_start = self.client.post(
            "/quiz/start",
            json={"workspace_id": index["workspace_id"], "concept_ids": ["grounding"]},
        )
        start_payloads = parse_sse_payloads(quiz_start.text)
        question = next(payload for payload in start_payloads if payload["event"] == "question")
        self.assertIn("#", question["source_anchor"])

        quiz_answer = self.client.post(
            "/quiz/answer",
            json={
                "workspace_id": index["workspace_id"],
                "attempt_id": question["attempt_id"],
                "chosen_index": 0,
            },
        )
        answer_payloads = parse_sse_payloads(quiz_answer.text)
        events = [payload["event"] for payload in answer_payloads]
        self.assertEqual(events, ["graded", "quiz_done"])
        graded = answer_payloads[0]
        self.assertTrue(graded["is_correct"])
        self.assertEqual(graded["chip"]["anchor"], question["source_anchor"])

        notebook = self.client.get("/notebook", params={"workspace_id": index["workspace_id"]})
        artifacts = notebook.json()["artifacts"]
        self.assertTrue(any(artifact["kind"] == "quiz_result" for artifact in artifacts))

        artifact_id = answer_payloads[1]["artifact_id"]
        artifact = self.client.get(
            f"/artifact/{artifact_id}",
            params={"workspace_id": index["workspace_id"]},
        )
        self.assertEqual(artifact.status_code, 200)

        file_id, locator = question["source_anchor"].split("#", 1)
        source = self.client.get(
            f"/source/{file_id}/{locator}",
            params={"workspace_id": index["workspace_id"]},
        )
        self.assertEqual(source.status_code, 200)
        self.assertTrue(source.json()["text"])

    @patch("backend.main.llm_client", new_callable=lambda: FakeLLMClient())
    def test_workspace_registry_and_artifacts_survive_restart(self, _fake_llm) -> None:
        ws = self.base / "restart"
        build_csv_workspace(ws)
        index = self.client.post("/index", json={"folder_path": str(ws)}).json()
        self.client.get(index["events"])
        ask = self.client.post(
            "/ask",
            json={"workspace_id": index["workspace_id"], "question": "Why does Trial 4 look different?"},
        )
        ask_payloads = parse_sse_payloads(ask.text)
        script_artifact = next(
            payload for payload in ask_payloads if payload["event"] == "artifact" and payload["kind"] == "script"
        )

        workspace_manager._cache.clear()
        reloaded_manager = WorkspaceManager(workspace_manager.registry_path)
        record = reloaded_manager.get(index["workspace_id"])
        self.assertIsNotNone(record)
        self.assertTrue(record.db_path.exists())

        notebook = self.client.get("/notebook", params={"workspace_id": index["workspace_id"]})
        self.assertTrue(
            any(artifact["id"] == script_artifact["artifact_id"] for artifact in notebook.json()["artifacts"])
        )

    @patch("backend.main.llm_client", new_callable=lambda: DeterministicFakeLLMClient())
    def test_fake_mode_title_extraction(self, _fake_llm) -> None:
        ws = self.base / "title"
        build_workspace(
            ws,
            "Physics_Textbook_Chapter_01.pdf",
            "%PDF-1.4\nPhysics textbook chapter 01 discusses pendulums.\n",
        )

        index = self.client.post("/index", json={"folder_path": str(ws)}).json()
        self.client.get(index["events"])
        ask = self.client.post(
            "/ask",
            json={"workspace_id": index["workspace_id"], "question": "What is the title of this book?"},
        )
        payloads = parse_sse_payloads(ask.text)
        answer = "".join(payload["text"] for payload in payloads if payload["event"] == "token")
        self.assertIn("Detected title: Physics Textbook Chapter 01", answer)

    @patch("backend.main.llm_client", new_callable=lambda: DeterministicFakeLLMClient())
    def test_fake_mode_file_count_and_document_listing(self, _fake_llm) -> None:
        ws = self.base / "listing"
        build_workspace(ws, "alpha.txt", "alpha topic only")
        build_workspace(ws, "beta.pdf", "%PDF-1.4\nbeta topic only\n")
        build_workspace(ws, "gamma.md", "# Gamma\ncontent")

        index = self.client.post("/index", json={"folder_path": str(ws)}).json()
        self.client.get(index["events"])

        count_response = self.client.post(
            "/ask",
            json={"workspace_id": index["workspace_id"], "question": "How many files are indexed?"},
        )
        count_payloads = parse_sse_payloads(count_response.text)
        count_answer = "".join(payload["text"] for payload in count_payloads if payload["event"] == "token")
        self.assertIn("3 files are indexed.", count_answer)

        list_response = self.client.post(
            "/ask",
            json={"workspace_id": index["workspace_id"], "question": "List every document."},
        )
        list_payloads = parse_sse_payloads(list_response.text)
        list_answer = "".join(payload["text"] for payload in list_payloads if payload["event"] == "token")
        self.assertIn("- alpha.txt", list_answer)
        self.assertIn("- beta.pdf", list_answer)
        self.assertIn("- gamma.md", list_answer)

        pdf_response = self.client.post(
            "/ask",
            json={"workspace_id": index["workspace_id"], "question": "What PDFs are available?"},
        )
        pdf_payloads = parse_sse_payloads(pdf_response.text)
        pdf_answer = "".join(payload["text"] for payload in pdf_payloads if payload["event"] == "token")
        self.assertIn("- beta.pdf", pdf_answer)
        self.assertNotIn("alpha.txt", pdf_answer)

    @patch("backend.main.llm_client", new_callable=lambda: DeterministicFakeLLMClient())
    def test_fake_mode_deterministic_summary(self, _fake_llm) -> None:
        ws = self.base / "summary"
        build_workspace(
            ws,
            "notes.txt",
            (
                "Pendulums show periodic motion. "
                "Trial 4 decays faster than the others. "
                "Trial 4 decays faster than the others. "
                "Damping changes the amplitude over time."
            ),
        )

        index = self.client.post("/index", json={"folder_path": str(ws)}).json()
        self.client.get(index["events"])
        ask = self.client.post(
            "/ask",
            json={"workspace_id": index["workspace_id"], "question": "Summarize this chapter."},
        )
        payloads = parse_sse_payloads(ask.text)
        answer = "".join(payload["text"] for payload in payloads if payload["event"] == "token")
        self.assertIn("Pendulums show periodic motion.", answer)
        self.assertIn("Trial 4 decays faster than the others.", answer)
        self.assertEqual(answer.count("Trial 4 decays faster than the others."), 1)

    @patch("backend.main.llm_client", new_callable=lambda: DeterministicFakeLLMClient())
    def test_fake_mode_unknown_question_handling(self, _fake_llm) -> None:
        ws = self.base / "unknown"
        build_workspace(ws, "notes.txt", "This workspace discusses pendulum damping only.")

        index = self.client.post("/index", json={"folder_path": str(ws)}).json()
        self.client.get(index["events"])
        ask = self.client.post(
            "/ask",
            json={"workspace_id": index["workspace_id"], "question": "What does this workspace say about mitochondria?"},
        )
        payloads = parse_sse_payloads(ask.text)
        answer = "".join(payload["text"] for payload in payloads if payload["event"] == "token")
        self.assertEqual(
            answer,
            "I couldn't find enough supporting information in the indexed workspace.",
        )

    def test_sse_invalid_workspace_returns_stable_error(self) -> None:
        payloads = parse_sse_payloads(
            self.client.post("/ask", json={"workspace_id": "missing", "question": "hello"}).text
        )
        error = payloads[-1]
        self.assertEqual(error["event"], "error")
        self.assertEqual(error["code"], "WORKSPACE_NOT_FOUND")
        self.assertEqual(error["message"], "Selected workspace was not found.")
        self.assertIn("request_id", error)
        self.assertNotIn("Traceback", json.dumps(error))

    def test_sse_sandbox_failure_is_stable_and_logs_diagnostics(self) -> None:
        class BrokenScriptLLM(FakeLLMClient):
            def generate_analysis_script(self, *, question: str, retrieval_results, dataset_profiles_json: str):
                return type(
                    "AnalysisScript",
                    (),
                    {
                        "target_file_path": "pendulum.csv",
                        "title": "Broken",
                        "needs_chart": False,
                        "script": "write_result('bad payload')\n",
                    },
                )()

        ws = self.base / "sandbox_fail"
        build_csv_workspace(ws)
        index = self.client.post("/index", json={"folder_path": str(ws)}).json()
        self.client.get(index["events"])
        with (
            patch("backend.main.llm_client", new=BrokenScriptLLM()),
            self.assertLogs("fieldnotes.api", level="ERROR") as logs,
        ):
            payloads = parse_sse_payloads(
                self.client.post(
                    "/ask",
                    json={"workspace_id": index["workspace_id"], "question": "Why trial 4?"},
                ).text
            )
        error = payloads[-1]
        self.assertEqual(error["code"], "SANDBOX_ERROR")
        self.assertNotIn(str(ws), error["message"])
        self.assertNotIn("Traceback", json.dumps(error))
        self.assertTrue(any("Result payload must be dictionary" in line for line in logs.output))

    def test_sse_live_api_failure_is_stable(self) -> None:
        class FailingLLM(FakeLLMClient):
            def classify_intent(self, question: str) -> RouteIntentSchema:
                raise RuntimeError("OpenAI Responses API failed for gpt-5 at /private/secret")

        ws = self.base / "live_api_fail"
        build_workspace(ws, "alpha.txt", "alpha")
        index = self.client.post("/index", json={"folder_path": str(ws)}).json()
        self.client.get(index["events"])
        with patch("backend.main.llm_client", new=FailingLLM()):
            payloads = parse_sse_payloads(
                self.client.post("/ask", json={"workspace_id": index["workspace_id"], "question": "hello"}).text
            )
        error = payloads[-1]
        self.assertEqual(error["code"], "LIVE_API_UNAVAILABLE")
        self.assertNotIn("gpt-5", error["message"])
        self.assertNotIn("/private/secret", error["message"])

    def test_sse_timeout_failure_is_stable(self) -> None:
        class TimeoutLLM(FakeLLMClient):
            def classify_intent(self, question: str) -> RouteIntentSchema:
                raise TimeoutError("timed out at /private/data")

        ws = self.base / "timeout_fail"
        build_workspace(ws, "alpha.txt", "alpha")
        index = self.client.post("/index", json={"folder_path": str(ws)}).json()
        self.client.get(index["events"])
        with patch("backend.main.llm_client", new=TimeoutLLM()):
            payloads = parse_sse_payloads(
                self.client.post("/ask", json={"workspace_id": index["workspace_id"], "question": "hello"}).text
            )
        error = payloads[-1]
        self.assertEqual(error["code"], "TIMEOUT")
        self.assertNotIn("/private/data", error["message"])

    def test_rest_sqlite_failure_is_stable_and_logs_diagnostics(self) -> None:
        with (
            patch("backend.main.connect_sqlite", side_effect=sqlite3.DatabaseError("db broke at /private/work.db")),
            patch.object(workspace_manager, "get", return_value=type("Record", (), {"db_path": Path("x"), "artifacts_dir": Path("x"), "root": Path("x")})()),
            self.assertLogs("fieldnotes.api", level="ERROR") as logs,
        ):
            response = self.client.get("/notebook", params={"workspace_id": "ws"})

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["code"], "DATABASE_ERROR")
        self.assertNotIn("/private/work.db", response.text)
        self.assertTrue(any("DatabaseError" in line for line in logs.output))

    def test_sse_unexpected_exception_is_stable(self) -> None:
        class ExplodingLLM(FakeLLMClient):
            def classify_intent(self, question: str) -> RouteIntentSchema:
                raise RuntimeError("Traceback: boom at /private/project")

        ws = self.base / "explode"
        build_workspace(ws, "alpha.txt", "alpha")
        index = self.client.post("/index", json={"folder_path": str(ws)}).json()
        self.client.get(index["events"])
        with patch("backend.main.llm_client", new=ExplodingLLM()):
            payloads = parse_sse_payloads(
                self.client.post("/ask", json={"workspace_id": index["workspace_id"], "question": "hello"}).text
            )
        error = payloads[-1]
        self.assertEqual(error["code"], "INTERNAL_ERROR")
        self.assertNotIn("Traceback", json.dumps(error))
        self.assertNotIn("/private/project", json.dumps(error))

    def test_fake_llm_extract_concepts_returns_valid_concept_updates(self) -> None:
        retrieval_results = [
            RetrievalChunk(
                chunk="Grounded passage about oscillation and damping.",
                score=1.0,
                anchor="block1/b1",
                file_id="file_alpha",
                relative_path="alpha.txt",
            )
        ]

        updates = DeterministicFakeLLMClient().extract_concepts(
            "What concept matters here?",
            retrieval_results,
        )

        self.assertTrue(updates)
        self.assertTrue(all(isinstance(update, ConceptUpdate) for update in updates))
        self.assertTrue(all(update.concept_id for update in updates))
        self.assertTrue(all(update.name for update in updates))
        self.assertTrue(all(update.state in {"touched", "shaky"} for update in updates))


if __name__ == "__main__":
    unittest.main()
