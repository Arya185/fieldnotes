from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("OPENAI_API_KEY", "test-key")

from backend.db import BASE_SCHEMA_SQL, connect_sqlite, initialize_schema
from backend.indexer.bm25 import BM25Provider
from backend.indexer.embeddings import EmbeddingService
from backend.indexer.evaluation import RetrievalBenchmark, evaluate_benchmarks
from backend.indexer.events import EventStreamHub
from backend.indexer.pipeline import run_indexing
from backend.indexer.vectors import HybridProvider, SQLiteVectorProvider, cosine_similarity
from backend.storage import file_id_for_path, load_chunk_by_anchor


def build_workspace(root: Path, filename: str, contents: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / filename).write_text(contents, encoding="utf-8")


class CountingProvider:
    def __init__(self) -> None:
        self.calls = 0

    def embed(self, text: str, *, model: str) -> list[float]:
        self.calls += 1
        size = len(text.split()) or 1
        return [float(size), 1.0, 0.0]


class Phase2EmbeddingsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_initialize_schema_migrates_legacy_database(self) -> None:
        workspace = self.base / "legacy"
        fieldnotes_dir = workspace / ".fieldnotes"
        fieldnotes_dir.mkdir(parents=True, exist_ok=True)
        db_path = fieldnotes_dir / "fieldnotes.db"

        connection = sqlite3.connect(db_path)
        connection.executescript(BASE_SCHEMA_SQL)
        connection.commit()
        connection.close()

        migrated = connect_sqlite(db_path)
        try:
            initialize_schema(migrated)
            version_row = migrated.execute(
                "SELECT version FROM schema_version ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
            self.assertIsNotNone(version_row)
            self.assertEqual(int(version_row["version"]), 2)
            table_row = migrated.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'embeddings'"
            ).fetchone()
            self.assertIsNotNone(table_row)
        finally:
            migrated.close()

    def test_indexing_persists_embeddings_for_chunks(self) -> None:
        workspace = self.base / "persist"
        build_workspace(workspace, "notes.txt", "alpha concept\n\nbeta concept\n\ngamma concept")

        run_indexing(workspace, "workspace_persist", EventStreamHub())

        connection = connect_sqlite(workspace / ".fieldnotes" / "fieldnotes.db")
        try:
            chunk_count = connection.execute("SELECT COUNT(*) AS count FROM chunks").fetchone()["count"]
            embedding_count = connection.execute("SELECT COUNT(*) AS count FROM embeddings").fetchone()["count"]
            embedding_row = connection.execute(
                "SELECT provider, model, content_hash, vector_json FROM embeddings LIMIT 1"
            ).fetchone()
            self.assertGreater(chunk_count, 0)
            self.assertEqual(embedding_count, chunk_count)
            self.assertEqual(str(embedding_row["provider"]), "deterministic")
            self.assertEqual(str(embedding_row["model"]), "hash-v1")
            self.assertTrue(str(embedding_row["content_hash"]))
            self.assertTrue(str(embedding_row["vector_json"]).startswith("["))
        finally:
            connection.close()

    def test_incremental_embedding_regeneration_updates_only_changed_chunks(self) -> None:
        workspace = self.base / "incremental"
        build_workspace(workspace, "notes.txt", "alpha concept\n\nbeta concept")

        run_indexing(workspace, "workspace_incremental", EventStreamHub())

        connection = connect_sqlite(workspace / ".fieldnotes" / "fieldnotes.db")
        try:
            file_id = file_id_for_path("notes.txt")
            alpha_before = load_chunk_by_anchor(connection, file_id, "block1/b1")
            beta_before = load_chunk_by_anchor(connection, file_id, "block2/b1")
            self.assertIsNotNone(alpha_before)
            self.assertIsNotNone(beta_before)
            before_rows = connection.execute(
                """
                SELECT chunk_id, content_hash
                FROM embeddings
                ORDER BY chunk_id
                """
            ).fetchall()
        finally:
            connection.close()

        build_workspace(workspace, "notes.txt", "alpha concept updated\n\nbeta concept")
        run_indexing(workspace, "workspace_incremental", EventStreamHub())

        connection = connect_sqlite(workspace / ".fieldnotes" / "fieldnotes.db")
        try:
            alpha_after = load_chunk_by_anchor(connection, file_id, "block1/b1")
            beta_after = load_chunk_by_anchor(connection, file_id, "block2/b1")
            self.assertIsNotNone(alpha_after)
            self.assertIsNotNone(beta_after)
            after_rows = connection.execute(
                """
                SELECT chunk_id, content_hash
                FROM embeddings
                ORDER BY chunk_id
                """
            ).fetchall()
        finally:
            connection.close()

        before_hashes = {str(row["chunk_id"]): str(row["content_hash"]) for row in before_rows}
        after_hashes = {str(row["chunk_id"]): str(row["content_hash"]) for row in after_rows}
        self.assertEqual(set(before_hashes), set(after_hashes))
        self.assertNotEqual(before_hashes[str(alpha_after["id"])], after_hashes[str(alpha_after["id"])])
        self.assertEqual(before_hashes[str(beta_after["id"])], after_hashes[str(beta_after["id"])])

    def test_cosine_similarity_ranking_orders_semantic_match_first(self) -> None:
        workspace = self.base / "vector-rank"
        build_workspace(workspace, "alpha.txt", "pendulum damping ratio decay")
        build_workspace(workspace, "beta.txt", "supply chain finance inventory")
        run_indexing(workspace, "workspace_vector_rank", EventStreamHub())

        connection = connect_sqlite(workspace / ".fieldnotes" / "fieldnotes.db")
        try:
            provider = SQLiteVectorProvider(connection)
            results = provider.search("damping ratio", limit=5)
        finally:
            connection.close()

        self.assertTrue(results)
        self.assertEqual(results[0].relative_path, "alpha.txt")
        self.assertEqual(results[0].diagnostics["method"], "vector")

    def test_hybrid_score_fusion_combines_bm25_and_vector_signals(self) -> None:
        workspace = self.base / "hybrid-fusion"
        build_workspace(workspace, "alpha.txt", "pendulum damping ratio decay")
        build_workspace(workspace, "beta.txt", "pendulum theory overview")
        run_indexing(workspace, "workspace_hybrid_fusion", EventStreamHub())

        connection = connect_sqlite(workspace / ".fieldnotes" / "fieldnotes.db")
        try:
            provider = HybridProvider(connection, mode="hybrid", bm25_weight=0.8, vector_weight=0.2)
            results = provider.search("pendulum damping", limit=5)
        finally:
            connection.close()

        self.assertTrue(results)
        self.assertEqual(results[0].relative_path, "alpha.txt")
        self.assertIn("bm25_score", results[0].diagnostics)
        self.assertIn("vector_score", results[0].diagnostics)
        self.assertIn("fused_score", results[0].diagnostics)

    def test_query_embedding_cache_reuses_vector_and_separates_model_scope(self) -> None:
        service = EmbeddingService(provider_name="deterministic", model_name="hash-v1")
        counter = CountingProvider()
        object.__setattr__(service, "_provider", counter)

        first = service.embed_query("same query")
        second = service.embed_query("same query")
        self.assertEqual(first, second)
        self.assertEqual(counter.calls, 1)

        other_model = EmbeddingService(provider_name="deterministic", model_name="hash-v2")
        other_counter = CountingProvider()
        object.__setattr__(other_model, "_provider", other_counter)
        other_model.embed_query("same query")
        self.assertEqual(other_counter.calls, 1)

    def test_bm25_only_mode_keeps_bm25_ordering(self) -> None:
        workspace = self.base / "bm25-only"
        build_workspace(workspace, "alpha.txt", "pendulum damping ratio")
        build_workspace(workspace, "beta.txt", "pendulum basics")
        run_indexing(workspace, "workspace_bm25_only", EventStreamHub())

        connection = connect_sqlite(workspace / ".fieldnotes" / "fieldnotes.db")
        try:
            bm25_results = BM25Provider(connection).search("damping ratio", limit=5)
            hybrid_bm25 = HybridProvider(connection, mode="bm25", bm25_weight=1.0, vector_weight=0.0)
            fused_results = hybrid_bm25.search("damping ratio", limit=5)
        finally:
            connection.close()

        self.assertEqual([row.anchor for row in bm25_results], [row.anchor for row in fused_results])

    def test_vector_only_mode_returns_vector_results(self) -> None:
        workspace = self.base / "vector-only"
        build_workspace(workspace, "alpha.txt", "resonance frequency damping")
        build_workspace(workspace, "beta.txt", "market segmentation revenue")
        run_indexing(workspace, "workspace_vector_only", EventStreamHub())

        connection = connect_sqlite(workspace / ".fieldnotes" / "fieldnotes.db")
        try:
            provider = HybridProvider(connection, mode="vector")
            results = provider.search("frequency damping", limit=5)
        finally:
            connection.close()

        self.assertTrue(results)
        self.assertEqual(results[0].relative_path, "alpha.txt")
        self.assertEqual(results[0].diagnostics["method"], "vector")

    def test_hybrid_mode_returns_fused_results(self) -> None:
        workspace = self.base / "hybrid-mode"
        build_workspace(workspace, "alpha.txt", "pendulum damping ratio")
        build_workspace(workspace, "beta.txt", "pendulum lab notes")
        run_indexing(workspace, "workspace_hybrid_mode", EventStreamHub())

        connection = connect_sqlite(workspace / ".fieldnotes" / "fieldnotes.db")
        try:
            provider = HybridProvider(connection, mode="hybrid", bm25_weight=0.5, vector_weight=0.5)
            results = provider.search("pendulum damping", limit=5)
        finally:
            connection.close()

        self.assertTrue(results)
        self.assertEqual(results[0].diagnostics["method"], "hybrid")

    def test_retrieval_metrics_report_expected_scores(self) -> None:
        workspace = self.base / "metrics"
        build_workspace(workspace, "alpha.txt", "pendulum damping ratio")
        build_workspace(workspace, "beta.txt", "supply chain logistics")
        run_indexing(workspace, "workspace_metrics", EventStreamHub())

        connection = connect_sqlite(workspace / ".fieldnotes" / "fieldnotes.db")
        try:
            provider = HybridProvider(connection, mode="vector")
            file_id = file_id_for_path("alpha.txt")
            benchmarks = [
                RetrievalBenchmark(
                    query="damping ratio",
                    relevant_anchors={f"{file_id}#block1/b1"},
                )
            ]
            metrics = evaluate_benchmarks(provider, benchmarks)
        finally:
            connection.close()

        self.assertEqual(metrics.recall_at_5, 1.0)
        self.assertEqual(metrics.recall_at_10, 1.0)
        self.assertEqual(metrics.mrr, 1.0)

    def test_cosine_similarity_handles_identical_vectors(self) -> None:
        self.assertAlmostEqual(cosine_similarity([1.0, 0.0], [1.0, 0.0]), 1.0)


if __name__ == "__main__":
    unittest.main()
