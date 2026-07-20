from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("FIELDNOTES_USE_FAKE_LLM", "1")

from fastapi.testclient import TestClient

from backend.indexer.bm25 import RetrievalChunk
from backend.main import app
from backend.models import ConceptUpdate, QuizQuestionSchema, RouteIntentSchema


class FakeLLMClient:
    def classify_intent(self, question: str) -> RouteIntentSchema:
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


def parse_sse_payloads(response_text: str) -> list[dict]:
    payloads: list[dict] = []
    for block in response_text.split("\n\n"):
        if not block.strip():
            continue
        if not block.startswith("data: "):
            continue
        payloads.append(json.loads(block[6:]))
    return payloads


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


class QuizEdgeCaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base = Path(self.temp_dir.name)
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    @patch("backend.main.llm_client", new_callable=lambda: FakeLLMClient())
    def test_quiz_answer_unknown_attempt_returns_stable_error(self, _fake_llm) -> None:
        ws = self.base / "quiz-missing-attempt"
        build_csv_workspace(ws)
        index = self.client.post("/index", json={"folder_path": str(ws)}).json()
        self.client.get(index["events"])

        payloads = parse_sse_payloads(
            self.client.post(
                "/quiz/answer",
                json={
                    "workspace_id": index["workspace_id"],
                    "attempt_id": "attempt_missing",
                    "chosen_index": 0,
                },
            ).text
        )

        error = payloads[-1]
        self.assertEqual(error["event"], "error")
        self.assertEqual(error["code"], "INVALID_REQUEST")
        self.assertEqual(error["message"], "Requested quiz attempt was not found.")
        self.assertIn("request_id", error)

    @patch("backend.main.llm_client", new_callable=lambda: FakeLLMClient())
    def test_quiz_answer_cannot_be_submitted_twice(self, _fake_llm) -> None:
        ws = self.base / "quiz-repeat-answer"
        build_csv_workspace(ws)
        index = self.client.post("/index", json={"folder_path": str(ws)}).json()
        self.client.get(index["events"])

        quiz_start = self.client.post(
            "/quiz/start",
            json={"workspace_id": index["workspace_id"], "concept_ids": ["grounding"]},
        )
        question = next(
            payload for payload in parse_sse_payloads(quiz_start.text) if payload["event"] == "question"
        )

        first_answer = self.client.post(
            "/quiz/answer",
            json={
                "workspace_id": index["workspace_id"],
                "attempt_id": question["attempt_id"],
                "chosen_index": 0,
            },
        )
        first_payloads = parse_sse_payloads(first_answer.text)
        self.assertEqual([payload["event"] for payload in first_payloads], ["graded", "quiz_done"])

        second_answer = self.client.post(
            "/quiz/answer",
            json={
                "workspace_id": index["workspace_id"],
                "attempt_id": question["attempt_id"],
                "chosen_index": 1,
            },
        )
        second_payloads = parse_sse_payloads(second_answer.text)
        error = second_payloads[-1]
        self.assertEqual(error["event"], "error")
        self.assertEqual(error["code"], "INVALID_REQUEST")
        self.assertEqual(error["message"], "Quiz attempt has already been answered.")
        self.assertIn("request_id", error)

    def test_quiz_answer_missing_payload_field_returns_stable_422(self) -> None:
        response = self.client.post(
            "/quiz/answer",
            json={"workspace_id": "ws", "attempt_id": "attempt_only"},
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["code"], "INVALID_REQUEST")
        self.assertEqual(response.json()["message"], "Request payload is invalid.")
        self.assertIn("request_id", response.json())

    def test_quiz_answer_malformed_json_returns_stable_422(self) -> None:
        response = self.client.post(
            "/quiz/answer",
            content='{"workspace_id":"ws","attempt_id":"attempt","chosen_index":',
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["code"], "INVALID_REQUEST")
        self.assertEqual(response.json()["message"], "Request payload is invalid.")
        self.assertIn("request_id", response.json())


if __name__ == "__main__":
    unittest.main()
