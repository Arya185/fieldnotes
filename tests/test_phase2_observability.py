from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("FIELDNOTES_USE_FAKE_LLM", "1")

from backend.indexer.bm25 import RetrievalChunk
from backend.indexer.inspection import inspect_retrieval
from backend.indexer.reranker import RerankDecision, RerankResult
from backend.telemetry.tracing import (
    LogContext,
    MetricsRegistry,
    TraceCollector,
    load_benchmark_results,
    metrics_registry,
    structured_log,
)
from scripts import run_benchmarks as benchmark_module


def _successful_command(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(command, 0, "", "")


class Phase2ObservabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base = Path(self.temp_dir.name)
        metrics_registry.values.clear()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()
        metrics_registry.values.clear()

    def test_trace_generation(self) -> None:
        collector = TraceCollector(enabled=True, verbose=True)
        with collector.span("planning", question="why", intent="analyze") as metadata:
            metadata["step_count"] = 3
        spans = collector.snapshot()
        self.assertEqual(len(spans), 1)
        self.assertEqual(spans[0].span_type, "planning")
        self.assertEqual(spans[0].status, "ok")
        self.assertEqual(spans[0].metadata["step_count"], 3)

    def test_metric_collection(self) -> None:
        registry = MetricsRegistry(enabled=True)
        registry.record("retrieval_latency_ms", 10)
        registry.record("retrieval_latency_ms", 20)
        snapshot = registry.snapshot()
        self.assertEqual(snapshot["retrieval_latency_ms"]["count"], 2.0)
        self.assertEqual(snapshot["retrieval_latency_ms"]["avg"], 15.0)

    def test_retrieval_inspection(self) -> None:
        candidate = _chunk("file_a", "alpha.txt", "block1/b1", "alpha text")
        selected = _chunk("file_a", "alpha.txt", "block1/b1", "alpha text", reranked_rank=1)
        discarded = _chunk("file_b", "beta.txt", "block1/b1", "beta text")
        inspection = inspect_retrieval(
            [candidate, discarded],
            RerankResult(
                selected_chunks=[selected],
                decisions=[
                    RerankDecision(selected, 1, 1, 0.9, True, "selected_diverse_context"),
                    RerankDecision(discarded, 2, None, 0.2, False, "diversity_not_selected"),
                ],
            ),
        )
        self.assertEqual(len(inspection.candidate_chunks), 2)
        self.assertEqual(len(inspection.reranked_chunks), 1)
        self.assertEqual(inspection.discarded_chunks[0]["reason"], "diversity_not_selected")

    def test_structured_logging(self) -> None:
        line = structured_log(
            component="planner",
            severity="info",
            message="planned request",
            context=LogContext(
                workspace_id="ws_1",
                run_id="run_1",
                request_id="req_1",
                trace_id="trace_1",
            ),
            metadata={"step_count": 3},
        )
        payload = json.loads(line)
        self.assertEqual(payload["workspace_id"], "ws_1")
        self.assertEqual(payload["component"], "planner")
        self.assertEqual(payload["metadata"]["step_count"], 3)

    def test_benchmark_runner(self) -> None:
        results_path = self.base / "benchmarks.json"
        original_path = benchmark_module.RESULTS_PATH
        original_release_path = benchmark_module.RELEASE_RESULTS_PATH
        benchmark_module.RESULTS_PATH = results_path
        benchmark_module.RELEASE_RESULTS_PATH = self.base / "release_benchmarks.json"
        try:
            with patch.object(benchmark_module, "npm_command", return_value=["npm", "run", "build"]):
                result = benchmark_module.run_benchmarks(command_runner=_successful_command)
        finally:
            benchmark_module.RESULTS_PATH = original_path
            benchmark_module.RELEASE_RESULTS_PATH = original_release_path
        self.assertIn("latency_summary", result)
        self.assertIn("retrieval_metrics", result)
        self.assertIn("retrieval_quality_eval", result)
        self.assertIn("execution_metrics", result)
        self.assertTrue(results_path.exists())
        loaded = load_benchmark_results(results_path)
        self.assertEqual(result["execution_metrics"], loaded["execution_metrics"])

    def test_regression_fixtures(self) -> None:
        fixture = json.loads((Path("tests/fixtures/observability_fixture.json")).read_text(encoding="utf-8"))
        line = structured_log(
            component="executor",
            severity="warning",
            message="fixture check",
            context=LogContext(workspace_id="ws", run_id="run", request_id="req", trace_id="trace"),
            metadata={},
        )
        payload = json.loads(line)
        self.assertEqual(sorted(payload.keys()), fixture["structured_log_keys"])

        results_path = self.base / "fixture_benchmarks.json"
        original_path = benchmark_module.RESULTS_PATH
        original_release_path = benchmark_module.RELEASE_RESULTS_PATH
        benchmark_module.RESULTS_PATH = results_path
        benchmark_module.RELEASE_RESULTS_PATH = self.base / "release_benchmarks.json"
        try:
            with patch.object(benchmark_module, "npm_command", return_value=["npm", "run", "build"]):
                result = benchmark_module.run_benchmarks(command_runner=_successful_command)
        finally:
            benchmark_module.RESULTS_PATH = original_path
            benchmark_module.RELEASE_RESULTS_PATH = original_release_path
        self.assertEqual(sorted(result.keys()), fixture["benchmark_keys"])


def _chunk(
    file_id: str,
    relative_path: str,
    anchor: str,
    text: str,
    *,
    reranked_rank: int | None = None,
) -> RetrievalChunk:
    return RetrievalChunk(
        chunk=text,
        score=0.5,
        anchor=anchor,
        file_id=file_id,
        relative_path=relative_path,
        diagnostics={"reranked_rank": reranked_rank},
    )


if __name__ == "__main__":
    unittest.main()
