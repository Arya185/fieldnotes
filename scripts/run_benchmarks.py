#!/usr/bin/env python3
"""Run internal Fieldnotes benchmarks."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend.agent.executor import Executor
from backend.agent.planner import ExecutionPlan, PlanStep, default_plan
from backend.config import FRONTEND_DIR, RELEASE_ARTIFACTS_DIR
from backend.db import connect_sqlite
from backend.indexer.evaluation import (
    ExecutionEvaluationCase,
    RetrievalBenchmark,
    compare_reranking,
    evaluate_execution_cases,
)
from backend.indexer.events import EventStreamHub
from backend.indexer.pipeline import run_indexing
from backend.indexer.reranker import DeterministicReranker
from backend.indexer.vectors import HybridProvider
from backend.release import FakeLLMClient
from backend.storage import file_id_for_path
from backend.telemetry.tracing import (
    LogContext,
    load_benchmark_results,
    metrics_registry,
    save_benchmark_results,
    structured_log,
)
from scripts.subprocess_utils import npm_command


RESULTS_PATH = ROOT_DIR / "scripts" / "benchmarks_latest.json"
RELEASE_RESULTS_PATH = RELEASE_ARTIFACTS_DIR / "release_benchmarks.json"


def build_csv_workspace(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "pendulum.csv").write_text(
        "trial,time,amplitude\n"
        "1,0,10\n1,1,9\n1,2,8\n"
        "2,0,10\n2,1,8.8\n2,2,7.9\n",
        encoding="utf-8",
    )
    (root / "notes.txt").write_text("Trial 2 damping explanation", encoding="utf-8")


def run_benchmarks(
    *,
    command_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict:
    previous = load_benchmark_results(RESULTS_PATH)
    metrics_registry.values.clear()
    RELEASE_ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    frontend_started = time.perf_counter()
    frontend_build = command_runner(
        npm_command("run", "build"),
        cwd=FRONTEND_DIR,
        capture_output=True,
        text=True,
        check=False,
    )
    frontend_build_ms = (time.perf_counter() - frontend_started) * 1000
    if frontend_build.returncode != 0:
        raise RuntimeError(
            f"Frontend build benchmark failed: {frontend_build.stderr.strip() or frontend_build.stdout.strip()}"
        )
    with tempfile.TemporaryDirectory() as temp_dir:
        workspace = Path(temp_dir) / "benchmark_workspace"
        build_csv_workspace(workspace)
        run_indexing(workspace, "workspace_benchmark", EventStreamHub())

        connection = connect_sqlite(workspace / ".fieldnotes" / "fieldnotes.db")
        try:
            provider = HybridProvider(connection, mode="hybrid", bm25_weight=0.5, vector_weight=0.5)
            reranker = DeterministicReranker()
            file_id = file_id_for_path("notes.txt")
            retrieval_comparison = compare_reranking(
                provider,
                reranker,
                [
                    RetrievalBenchmark(
                        query="damping explanation",
                        relevant_anchors={f"{file_id}#block1/b1"},
                        relevance_by_anchor={f"{file_id}#block1/b1": 2},
                    )
                ],
            )

            plan = ExecutionPlan(
                intent="analyze",
                rationale="benchmark fixture",
                steps=[
                    PlanStep(step_type="retrieve", label="retrieve", query="damping explanation", limit=5),
                    PlanStep(step_type="analyze", label="analyze"),
                    PlanStep(step_type="execute_python", label="execute"),
                    PlanStep(step_type="summarize", label="summarize"),
                    PlanStep(step_type="answer", label="answer"),
                ],
            )
            context = Executor().execute(
                plan=plan,
                question="Why damping changes?",
                workspace_root=workspace,
                artifacts_dir=workspace / ".fieldnotes" / "artifacts",
                db_path=workspace / ".fieldnotes" / "fieldnotes.db",
                answer_id="benchmark_answer",
                retrieval_provider=provider,
                llm_client=FakeLLMClient(),
            )
        finally:
            connection.close()

    execution_metrics = evaluate_execution_cases(
        [
            ExecutionEvaluationCase(
                completed=bool(context.intermediate_results.get("answer_context")),
                succeeded=not context.failures,
                citations_preserved=bool(context.retrieved_chunks),
                analysis_correct=bool(context.intermediate_results.get("python_result")),
            )
        ]
    )
    result = {
        "latency_summary": metrics_registry.snapshot(),
        "frontend_build_timing_ms": frontend_build_ms,
        "retrieval_metrics": {
            "before": retrieval_comparison.before.__dict__,
            "after": retrieval_comparison.after.__dict__,
        },
        "execution_metrics": execution_metrics.__dict__,
        "regression_comparison": build_regression(previous, metrics_registry.snapshot()),
    }
    save_benchmark_results(RESULTS_PATH, result)
    save_benchmark_results(RELEASE_RESULTS_PATH, result)
    return result


def build_regression(previous: dict | None, current_latency: dict) -> dict:
    if previous is None:
        return {"status": "no_previous_results"}
    prior_latency = previous.get("latency_summary", {})
    comparison: dict[str, dict[str, float]] = {}
    for key, current in current_latency.items():
        prior = prior_latency.get(key)
        if not prior:
            continue
        comparison[key] = {
            "avg_delta_ms": current["avg"] - prior["avg"],
            "max_delta_ms": current["max"] - prior["max"],
        }
    return comparison


def main() -> None:
    result = run_benchmarks()
    log_line = structured_log(
        component="benchmark_runner",
        severity="info",
        message="benchmarks complete",
        context=LogContext(workspace_id="benchmark_workspace", run_id="benchmark_run", request_id="benchmark_request", trace_id="benchmark_trace"),
        metadata={"result_path": str(RESULTS_PATH)},
    )
    print(log_line)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
