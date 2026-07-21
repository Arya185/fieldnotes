from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("FIELDNOTES_USE_FAKE_LLM", "1")

from backend.db import connect_sqlite
from backend.indexer.bm25 import RetrievalChunk
from backend.indexer.embeddings import EmbeddingService
from backend.indexer.evaluation import RetrievalBenchmark, compare_reranking
from backend.indexer.events import EventStreamHub
from backend.indexer.pipeline import run_indexing
from backend.indexer.reranker import DeterministicReranker
from backend.indexer.vectors import HybridProvider
from backend.storage import file_id_for_path
from scripts.run_benchmarks import DEMO_COURSE_RETRIEVAL_FIXTURE_PATH, load_retrieval_fixture


def build_workspace(root: Path, filename: str, contents: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / filename).write_text(contents, encoding="utf-8")


class Phase2RerankerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.demo_course_temp_dir = tempfile.TemporaryDirectory()
        cls.demo_course_workspace = Path(cls.demo_course_temp_dir.name) / "demo_course"
        shutil.copytree(
            Path("demo_course"),
            cls.demo_course_workspace,
            ignore=shutil.ignore_patterns(".fieldnotes"),
        )
        run_indexing(cls.demo_course_workspace, "workspace_demo_course_rerank", EventStreamHub())

    @classmethod
    def tearDownClass(cls) -> None:
        cls.demo_course_temp_dir.cleanup()
        super().tearDownClass()

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base = Path(self.temp_dir.name)
        self.reranker = DeterministicReranker(
            embedding_service=EmbeddingService(provider_name="deterministic", model_name="hash-v1"),
            max_retrieval_candidates=12,
            max_context_chunks=3,
            max_context_tokens=30,
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_reranking_stability(self) -> None:
        candidates = [
            _chunk("file_a", "alpha.txt", "block1/b1", "pendulum damping ratio"),
            _chunk("file_b", "beta.txt", "block1/b1", "pendulum lab note"),
        ]
        first = self.reranker.rerank("pendulum damping", candidates, limit=2)
        second = self.reranker.rerank("pendulum damping", candidates, limit=2)
        self.assertEqual(first.selected_chunks, second.selected_chunks)

    def test_duplicate_suppression(self) -> None:
        duplicate = _chunk("file_a", "alpha.txt", "block1/b1", "same chunk text")
        result = self.reranker.rerank(
            "same chunk",
            [duplicate, duplicate, _chunk("file_b", "beta.txt", "block1/b1", "other text")],
            limit=3,
        )
        keys = {(row.file_id, row.anchor) for row in result.selected_chunks}
        self.assertEqual(len(keys), len(result.selected_chunks))
        self.assertTrue(any(decision.reason == "duplicate_chunk" for decision in result.decisions))

    def test_context_budgeting_respects_chunk_and_token_limits(self) -> None:
        long_text = "token " * 40
        result = self.reranker.rerank(
            "token",
            [
                _chunk("file_a", "alpha.txt", "block1/b1", long_text),
                _chunk("file_b", "beta.txt", "block1/b1", "short token text"),
                _chunk("file_c", "gamma.txt", "block1/b1", "another short token text"),
            ],
            limit=3,
        )
        self.assertLessEqual(len(result.selected_chunks), 3)
        self.assertTrue(all(len(row.chunk.split()) <= 30 for row in result.selected_chunks))
        self.assertTrue(any(decision.reason == "context_token_limit" for decision in result.decisions))

    def test_diversity_selection_balances_files(self) -> None:
        candidates = [
            _chunk("file_a", "alpha.txt", "block1/b1", "pendulum damping ratio"),
            _chunk("file_a", "alpha.txt", "block2/b1", "pendulum damping extension"),
            _chunk("file_b", "beta.txt", "block1/b1", "pendulum theory"),
            _chunk("file_c", "gamma.txt", "block1/b1", "pendulum analysis"),
        ]
        result = self.reranker.rerank("pendulum damping", candidates, limit=3)
        self.assertEqual(len({row.relative_path for row in result.selected_chunks}), len(result.selected_chunks))

    def test_deterministic_ordering_breaks_ties_consistently(self) -> None:
        left = _chunk("file_a", "alpha.txt", "block1/b1", "shared text", bm25=1.0, vector=1.0, fused=1.0)
        right = _chunk("file_b", "beta.txt", "block1/b1", "shared text", bm25=1.0, vector=1.0, fused=1.0)
        result = self.reranker.rerank("shared", [right, left], limit=2)
        self.assertEqual([row.relative_path for row in result.selected_chunks], ["alpha.txt", "beta.txt"])

    def test_retrieval_quality_metrics_compare_before_after(self) -> None:
        workspace = self.base / "metrics"
        build_workspace(workspace, "alpha.txt", "pendulum damping ratio")
        build_workspace(workspace, "beta.txt", "pendulum overview notes")
        run_indexing(workspace, "workspace_metrics_rerank", EventStreamHub())

        connection = connect_sqlite(workspace / ".fieldnotes" / "fieldnotes.db")
        try:
            provider = HybridProvider(connection, mode="hybrid", bm25_weight=0.5, vector_weight=0.5)
            file_id = file_id_for_path("alpha.txt")
            comparison = compare_reranking(
                provider,
                self.reranker,
                [
                    RetrievalBenchmark(
                        query="pendulum damping",
                        relevant_anchors={f"{file_id}#block1/b1"},
                        relevance_by_anchor={f"{file_id}#block1/b1": 2},
                    )
                ],
                candidate_limit=10,
            )
        finally:
            connection.close()

        self.assertGreaterEqual(comparison.after.recall_at_5, comparison.before.recall_at_5)
        self.assertGreaterEqual(comparison.after.ndcg_at_5, 0.0)
        self.assertGreaterEqual(comparison.after.ndcg_at_10, 0.0)
        self.assertGreaterEqual(comparison.after.precision_at_5, 0.0)
        self.assertGreaterEqual(comparison.after.precision_at_10, 0.0)

    def test_demo_course_retrieval_fixture_loads_expected_anchor_pairs(self) -> None:
        payload = json.loads(DEMO_COURSE_RETRIEVAL_FIXTURE_PATH.read_text(encoding="utf-8"))
        benchmarks = load_retrieval_fixture(DEMO_COURSE_RETRIEVAL_FIXTURE_PATH)
        self.assertEqual(len(payload), len(benchmarks))
        self.assertGreaterEqual(len(benchmarks), 10)
        first_expected = f"{file_id_for_path(payload[0]['relative_path'])}#{payload[0]['anchor']}"
        self.assertEqual(benchmarks[0].relevant_anchors, {first_expected})

    def test_demo_course_retrieval_fixture_reports_precision_and_recall(self) -> None:
        connection = connect_sqlite(
            self.demo_course_workspace / ".fieldnotes" / "fieldnotes.db"
        )
        try:
            provider = HybridProvider(connection, mode="hybrid", bm25_weight=0.5, vector_weight=0.5)
            comparison = compare_reranking(
                provider,
                self.reranker,
                load_retrieval_fixture(DEMO_COURSE_RETRIEVAL_FIXTURE_PATH),
                candidate_limit=10,
            )
        finally:
            connection.close()

        self.assertGreaterEqual(comparison.before.recall_at_5, 0.0)
        self.assertLessEqual(comparison.before.recall_at_5, 1.0)
        self.assertGreaterEqual(comparison.after.recall_at_5, 0.0)
        self.assertLessEqual(comparison.after.recall_at_5, 1.0)
        self.assertGreaterEqual(comparison.before.precision_at_5, 0.0)
        self.assertLessEqual(comparison.before.precision_at_5, 1.0)
        self.assertGreaterEqual(comparison.after.precision_at_5, 0.0)
        self.assertLessEqual(comparison.after.precision_at_5, 1.0)

    def test_backward_compatibility_retrievalchunk_shape_unchanged(self) -> None:
        chunk = _chunk("file_a", "alpha.txt", "block1/b1", "pendulum damping")
        self.assertEqual(chunk.file_id, "file_a")
        self.assertEqual(chunk.anchor, "block1/b1")
        self.assertEqual(chunk.relative_path, "alpha.txt")


def _chunk(
    file_id: str,
    relative_path: str,
    anchor: str,
    text: str,
    *,
    bm25: float = 0.5,
    vector: float = 0.5,
    fused: float = 0.5,
) -> RetrievalChunk:
    return RetrievalChunk(
        chunk=text,
        score=fused,
        anchor=anchor,
        file_id=file_id,
        relative_path=relative_path,
        diagnostics={
            "method": "hybrid",
            "bm25_score": bm25,
            "vector_score": vector,
            "fused_score": fused,
        },
    )


if __name__ == "__main__":
    unittest.main()
