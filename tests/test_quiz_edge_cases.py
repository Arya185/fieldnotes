from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("FIELDNOTES_USE_FAKE_LLM", "1")
os.environ.setdefault("FIELDNOTES_RATE_LIMIT_DISABLED", "1")

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

    def generate_quiz_question(self, retrieval_results, concept_ids=None, difficulty="medium") -> QuizQuestionSchema:
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
        self.env_patcher = patch.dict(
            os.environ,
            {"FIELDNOTES_USE_FAKE_LLM": "1", "FIELDNOTES_RATE_LIMIT_DISABLED": "1"},
            clear=True,
        )
        self.env_patcher.start()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.env_patcher.stop()
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

    def _start_and_answer(self, workspace_id: str, *, correct: bool) -> str:
        """Start one quiz question, answer it, and return the question's difficulty."""
        start_payloads = parse_sse_payloads(
            self.client.post("/quiz/start", json={"workspace_id": workspace_id, "concept_ids": None}).text
        )
        question = next(p for p in start_payloads if p["event"] == "question")
        # FakeLLMClient always marks index 0 correct (see test-local FakeLLMClient above).
        chosen_index = 0 if correct else 1
        self.client.post(
            "/quiz/answer",
            json={"workspace_id": workspace_id, "attempt_id": question["attempt_id"], "chosen_index": chosen_index},
        )
        return question["difficulty"]

    @patch("backend.main.llm_client", new_callable=lambda: FakeLLMClient())
    def test_adaptive_quiz_all_correct_streak_raises_difficulty(self, _fake_llm) -> None:
        ws = self.base / "quiz-adaptive-correct"
        build_csv_workspace(ws)
        index = self.client.post("/index", json={"folder_path": str(ws)}).json()
        self.client.get(index["events"])
        workspace_id = index["workspace_id"]

        first_difficulty = self._start_and_answer(workspace_id, correct=True)
        second_difficulty = self._start_and_answer(workspace_id, correct=True)
        third_start = parse_sse_payloads(
            self.client.post("/quiz/start", json={"workspace_id": workspace_id, "concept_ids": None}).text
        )
        third_difficulty = next(p for p in third_start if p["event"] == "question")["difficulty"]

        self.assertEqual(first_difficulty, "medium")
        self.assertEqual(second_difficulty, "medium")
        self.assertEqual(third_difficulty, "hard")

    @patch("backend.main.llm_client", new_callable=lambda: FakeLLMClient())
    def test_adaptive_quiz_all_incorrect_streak_lowers_difficulty(self, _fake_llm) -> None:
        ws = self.base / "quiz-adaptive-incorrect"
        build_csv_workspace(ws)
        index = self.client.post("/index", json={"folder_path": str(ws)}).json()
        self.client.get(index["events"])
        workspace_id = index["workspace_id"]

        first_difficulty = self._start_and_answer(workspace_id, correct=False)
        second_start = parse_sse_payloads(
            self.client.post("/quiz/start", json={"workspace_id": workspace_id, "concept_ids": None}).text
        )
        second_question = next(p for p in second_start if p["event"] == "question")
        self.assertEqual(second_question["difficulty"], "easy")

        self.client.post(
            "/quiz/answer",
            json={
                "workspace_id": workspace_id,
                "attempt_id": second_question["attempt_id"],
                "chosen_index": 1,
            },
        )
        third_start = parse_sse_payloads(
            self.client.post("/quiz/start", json={"workspace_id": workspace_id, "concept_ids": None}).text
        )
        third_difficulty = next(p for p in third_start if p["event"] == "question")["difficulty"]

        self.assertEqual(first_difficulty, "medium")
        self.assertEqual(third_difficulty, "easy")

    @patch("backend.main.llm_client", new_callable=lambda: FakeLLMClient())
    def test_adaptive_quiz_mixed_performance_tracks_recent_accuracy(self, _fake_llm) -> None:
        ws = self.base / "quiz-adaptive-mixed"
        build_csv_workspace(ws)
        index = self.client.post("/index", json={"folder_path": str(ws)}).json()
        self.client.get(index["events"])
        workspace_id = index["workspace_id"]

        difficulties = [
            self._start_and_answer(workspace_id, correct=True),  # no history yet
            self._start_and_answer(workspace_id, correct=True),  # streak=1
            self._start_and_answer(workspace_id, correct=False),  # streak=2 -> hard question, then missed
            self._start_and_answer(workspace_id, correct=True),  # most recent was a miss -> easy question
        ]
        final_start = parse_sse_payloads(
            self.client.post("/quiz/start", json={"workspace_id": workspace_id, "concept_ids": None}).text
        )
        final_difficulty = next(p for p in final_start if p["event"] == "question")["difficulty"]

        self.assertEqual(difficulties, ["medium", "medium", "hard", "easy"])
        # most recent attempt was correct but only a streak of one -> back to medium
        self.assertEqual(final_difficulty, "medium")

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
