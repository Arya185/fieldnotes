from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("FIELDNOTES_USE_FAKE_LLM", "1")
os.environ.setdefault("FIELDNOTES_RATE_LIMIT_DISABLED", "1")

from fastapi.testclient import TestClient

from backend.db import connect_sqlite
from backend.indexer.events import EventStreamHub
from backend.indexer.pipeline import run_indexing
from backend.main import app
from backend.models import ConceptUpdate
from backend.services.concept_map import build_concept_map
from backend.storage import upsert_concept_updates


class ConceptMapGraphBuilderTests(unittest.TestCase):
    """Unit tests against a fixture concept log, no HTTP/indexing involved."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "fixture.db"
        self.connection = connect_sqlite(self.db_path, validate_integrity=False)
        from backend.db import initialize_schema

        initialize_schema(self.connection)

    def tearDown(self) -> None:
        self.connection.close()
        self.temp_dir.cleanup()

    def test_concepts_logged_under_same_answer_become_an_edge(self) -> None:
        upsert_concept_updates(
            self.connection,
            [
                ConceptUpdate(concept_id="concept_damping", name="damping", state="touched"),
                ConceptUpdate(concept_id="concept_period", name="period", state="touched"),
            ],
            source_anchor="file_a#p1/b1",
            answer_id="answer_1",
        )
        self.connection.commit()

        graph = build_concept_map(self.connection)

        node_ids = {node["id"] for node in graph["nodes"]}
        self.assertEqual(node_ids, {"concept_damping", "concept_period"})
        self.assertEqual(len(graph["edges"]), 1)
        edge = graph["edges"][0]
        self.assertEqual({edge["source"], edge["target"]}, {"concept_damping", "concept_period"})
        self.assertIn("answer", edge["reasons"])

    def test_concepts_from_different_answers_but_same_document_become_an_edge(self) -> None:
        upsert_concept_updates(
            self.connection,
            [ConceptUpdate(concept_id="concept_a", name="a", state="touched")],
            source_anchor="file_shared#p1/b1",
            answer_id="answer_1",
        )
        upsert_concept_updates(
            self.connection,
            [ConceptUpdate(concept_id="concept_b", name="b", state="touched")],
            source_anchor="file_shared#p2/b1",
            answer_id="answer_2",
        )
        self.connection.commit()

        graph = build_concept_map(self.connection)

        self.assertEqual(len(graph["edges"]), 1)
        edge = graph["edges"][0]
        self.assertEqual({edge["source"], edge["target"]}, {"concept_a", "concept_b"})
        self.assertEqual(edge["reasons"], ["document"])

    def test_unrelated_concepts_produce_no_edge(self) -> None:
        upsert_concept_updates(
            self.connection,
            [ConceptUpdate(concept_id="concept_x", name="x", state="touched")],
            source_anchor="file_x#p1/b1",
            answer_id="answer_1",
        )
        upsert_concept_updates(
            self.connection,
            [ConceptUpdate(concept_id="concept_y", name="y", state="shaky")],
            source_anchor="file_y#p1/b1",
            answer_id="answer_2",
        )
        self.connection.commit()

        graph = build_concept_map(self.connection)

        self.assertEqual(len(graph["nodes"]), 2)
        self.assertEqual(graph["edges"], [])
        states = {node["id"]: node["state"] for node in graph["nodes"]}
        self.assertEqual(states["concept_y"], "shaky")

    def test_repeated_co_occurrence_increases_edge_weight(self) -> None:
        # Two separate answers both pairing concept_a with concept_b: the
        # "same answer" reason fires once per answer (weight 2), plus one
        # more from the "same document" reason (both answers cite file_a,
        # which counts once as a presence fact, not per-repetition) = 3.
        for answer_id in ("answer_1", "answer_2"):
            upsert_concept_updates(
                self.connection,
                [
                    ConceptUpdate(concept_id="concept_a", name="a", state="touched"),
                    ConceptUpdate(concept_id="concept_b", name="b", state="touched"),
                ],
                source_anchor="file_a#p1/b1",
                answer_id=answer_id,
            )
        self.connection.commit()

        graph = build_concept_map(self.connection)

        self.assertEqual(len(graph["edges"]), 1)
        edge = graph["edges"][0]
        self.assertEqual(edge["weight"], 3)
        self.assertEqual(set(edge["reasons"]), {"answer", "document"})


def build_text_workspace(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "notes.md").write_text(
        "# Damped oscillation\n\nA damped oscillator loses energy over time.\n\n"
        "# Pendulum period\n\nThe period of a pendulum depends on its length.\n",
        encoding="utf-8",
    )


class ConceptMapEndpointTests(unittest.TestCase):
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

    def test_generate_concept_map_requires_existing_concepts(self) -> None:
        ws = self.base / "concept-map-empty"
        build_text_workspace(ws)
        index = self.client.post("/index", json={"folder_path": str(ws)}).json()
        self.client.get(index["events"])

        response = self.client.post("/concept-map/generate", json={"workspace_id": index["workspace_id"]})
        self.assertEqual(response.status_code, 422)

    def test_generate_concept_map_after_ask_persists_notebook_artifact(self) -> None:
        ws = self.base / "concept-map-ask"
        build_text_workspace(ws)
        index = self.client.post("/index", json={"folder_path": str(ws)}).json()
        self.client.get(index["events"])
        workspace_id = index["workspace_id"]

        ask_response = self.client.post(
            "/ask", json={"workspace_id": workspace_id, "question": "What is damping?"}
        )
        self.assertEqual(ask_response.status_code, 200)

        response = self.client.post("/concept-map/generate", json={"workspace_id": workspace_id})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertGreater(len(payload["nodes"]), 0)
        self.assertIsNotNone(payload["artifact_id"])

        notebook = self.client.get("/notebook", params={"workspace_id": workspace_id}).json()
        titles = [artifact["title"] for artifact in notebook["artifacts"]]
        self.assertIn("Concept map", titles)


if __name__ == "__main__":
    unittest.main()
