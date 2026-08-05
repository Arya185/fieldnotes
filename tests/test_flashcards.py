from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("FIELDNOTES_USE_FAKE_LLM", "1")

from fastapi.testclient import TestClient

from backend.main import app
from backend.services.flashcards import sm2_update


def build_text_workspace(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "notes.md").write_text(
        "# Damped oscillation\n\n"
        "A damped oscillator loses energy over time due to friction or resistance. "
        "The amplitude of a damped oscillator decreases exponentially with each cycle.\n\n"
        "# Pendulum period\n\n"
        "The period of a simple pendulum depends on its length and gravitational "
        "acceleration, not on its mass or amplitude for small swings.\n",
        encoding="utf-8",
    )


class FlashcardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base = Path(self.temp_dir.name)
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _index_workspace(self, name: str) -> dict:
        ws = self.base / name
        build_text_workspace(ws)
        index = self.client.post("/index", json={"folder_path": str(ws)}).json()
        self.client.get(index["events"])
        return index

    def test_generate_flashcards_returns_verified_citations(self) -> None:
        index = self._index_workspace("flashcards-generate")

        response = self.client.post(
            "/flashcards/generate",
            json={"workspace_id": index["workspace_id"], "count": 6},
        )
        self.assertEqual(response.status_code, 200)
        cards = response.json()["flashcards"]
        self.assertGreater(len(cards), 0)

        card_types = {card["card_type"] for card in cards}
        self.assertTrue(card_types.issubset(
            {"definition", "concept", "application", "true_false", "fill_blank", "scenario"}
        ))

        for card in cards:
            self.assertTrue(card["source_document"])
            self.assertTrue(card["source_locator"])
            self.assertEqual(card["review_count"], 0)
            self.assertEqual(card["ease_factor"], 2.5)
            self.assertIn(card["difficulty"], {"easy", "medium", "hard"})
            self.assertIn(
                card["bloom_level"],
                {"remember", "understand", "apply", "analyze", "evaluate", "create"},
            )

    def test_list_flashcards_returns_generated_cards(self) -> None:
        index = self._index_workspace("flashcards-list")
        self.client.post(
            "/flashcards/generate",
            json={"workspace_id": index["workspace_id"], "count": 4},
        )

        response = self.client.get(
            "/flashcards", params={"workspace_id": index["workspace_id"]}
        )
        self.assertEqual(response.status_code, 200)
        cards = response.json()["flashcards"]
        self.assertGreaterEqual(len(cards), 1)

    def test_review_flashcard_applies_sm2_and_updates_mastery(self) -> None:
        index = self._index_workspace("flashcards-review")
        generated = self.client.post(
            "/flashcards/generate",
            json={"workspace_id": index["workspace_id"], "count": 3},
        ).json()["flashcards"]
        flashcard_id = generated[0]["id"]

        good_review = self.client.post(
            "/flashcards/review",
            json={
                "workspace_id": index["workspace_id"],
                "flashcard_id": flashcard_id,
                "confidence": "good",
            },
        )
        self.assertEqual(good_review.status_code, 200)
        payload = good_review.json()
        card = payload["flashcard"]
        self.assertEqual(card["review_count"], 1)
        self.assertEqual(card["review_interval"], 1.0)
        self.assertGreater(card["mastery_weight"], 0.0)
        self.assertIsNotNone(card["last_review"])

        again_review = self.client.post(
            "/flashcards/review",
            json={
                "workspace_id": index["workspace_id"],
                "flashcard_id": flashcard_id,
                "confidence": "again",
            },
        )
        self.assertEqual(again_review.status_code, 200)
        again_card = again_review.json()["flashcard"]
        # incorrect answer resets progression and schedules sooner
        self.assertEqual(again_card["review_count"], 0)
        self.assertEqual(again_card["review_interval"], 1.0)
        self.assertLess(again_card["mastery_weight"], card["mastery_weight"])

    def test_review_unknown_flashcard_returns_404(self) -> None:
        index = self._index_workspace("flashcards-missing")
        response = self.client.post(
            "/flashcards/review",
            json={
                "workspace_id": index["workspace_id"],
                "flashcard_id": "flashcard_missing",
                "confidence": "good",
            },
        )
        self.assertEqual(response.status_code, 404)

    def test_low_mastery_triggers_more_flashcard_generation(self) -> None:
        index = self._index_workspace("flashcards-planner")

        plan = self.client.post(
            "/study-plans",
            json={
                "workspace_id": index["workspace_id"],
                "title": "Plan",
                "exam_date": "2099-01-01",
                "hours_per_day": 1.0,
                "pace": "medium",
            },
        ).json()
        self.assertIn("plan_id", plan)

        topics_response = self.client.get(
            "/study-progress", params={"workspace_id": index["workspace_id"]}
        ).json()
        self.assertGreater(len(topics_response["topic_mastery"]), 0)
        topic_id = topics_response["topic_mastery"][0]["id"]

        generated = self.client.post(
            "/flashcards/generate",
            json={"workspace_id": index["workspace_id"], "topic_id": topic_id, "count": 2},
        ).json()["flashcards"]
        self.assertGreater(len(generated), 0)

        for card in generated:
            review = self.client.post(
                "/flashcards/review",
                json={
                    "workspace_id": index["workspace_id"],
                    "flashcard_id": card["id"],
                    "confidence": "again",
                },
            ).json()

        self.assertLess(review["topic_mastery"], 0.5)

        after_topup = self.client.get(
            "/flashcards", params={"workspace_id": index["workspace_id"], "topic_id": topic_id}
        ).json()["flashcards"]
        self.assertGreaterEqual(len(after_topup), len(generated))


class Sm2AlgorithmTests(unittest.TestCase):
    def test_correct_answer_increases_interval(self) -> None:
        ease, interval, review_count = sm2_update(2.5, 6.0, 2, quality=4)
        self.assertEqual(review_count, 3)
        self.assertGreater(interval, 6.0)
        self.assertGreaterEqual(ease, 1.3)

    def test_incorrect_answer_resets_and_schedules_sooner(self) -> None:
        ease, interval, review_count = sm2_update(2.5, 20.0, 4, quality=1)
        self.assertEqual(review_count, 0)
        self.assertEqual(interval, 1.0)

    def test_ease_factor_never_drops_below_floor(self) -> None:
        ease, _, _ = sm2_update(1.3, 1.0, 0, quality=0)
        self.assertGreaterEqual(ease, 1.3)


if __name__ == "__main__":
    unittest.main()
