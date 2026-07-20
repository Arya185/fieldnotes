from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("OPENAI_API_KEY", "test-key")

from backend.agent.executor import Executor
from backend.agent.planner import ExecutionPlan, PlanStep, Planner, default_plan
from backend.db import connect_sqlite
from backend.indexer.evaluation import ExecutionEvaluationCase, evaluate_execution_cases
from backend.indexer.events import EventStreamHub
from backend.indexer.pipeline import run_indexing
from backend.indexer.vectors import HybridProvider
from backend.models import RouteIntentSchema
from backend.sandbox.runner import run_generated_analysis
from backend.storage import validate_citation_anchors


def build_csv_workspace(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "pendulum.csv").write_text(
        "trial,time,amplitude\n"
        "1,0,10\n1,1,9\n1,2,8\n"
        "2,0,10\n2,1,8.8\n2,2,7.9\n",
        encoding="utf-8",
    )
    (root / "notes.txt").write_text("Trial 2 damping explanation", encoding="utf-8")


class FakeResponsesClient:
    def __init__(self, output_text: str) -> None:
        self.output_text = output_text
        self.responses = self

    def create(self, **_kwargs):
        return type("Response", (), {"output_text": self.output_text})()


class FakeExecutorLLM:
    def generate_analysis_script(self, *, question: str, retrieval_results, dataset_profiles_json: str):
        profiles = json.loads(dataset_profiles_json)
        file_path = profiles[0]["file_path"]
        return type(
            "AnalysisScript",
            (),
            {
                "target_file_path": file_path,
                "title": "Fixture analysis",
                "needs_chart": True,
                "script": (
                    "import base64\n"
                    "import pandas as pd\n"
                    f"frame = pd.read_csv({file_path!r})\n"
                    "summary = {'rows': int(len(frame)), 'columns': list(frame.columns), 'mean_amplitude': float(frame['amplitude'].mean())}\n"
                    "png_bytes = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO7Z0XQAAAAASUVORK5CYII=')\n"
                    "write_chart_bytes(png_bytes)\n"
                    "write_result({'summary': 'analysis complete', 'metrics': summary})\n"
                ),
            },
        )()


class FailingExecutorLLM:
    def generate_analysis_script(self, *, question: str, retrieval_results, dataset_profiles_json: str):
        profiles = json.loads(dataset_profiles_json)
        file_path = profiles[0]["file_path"]
        return type(
            "AnalysisScript",
            (),
            {
                "target_file_path": file_path,
                "title": "Broken analysis",
                "needs_chart": False,
                "script": "raise RuntimeError('boom')\n",
            },
        )()


class Phase2PlannerExecutorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_planner_parses_structured_plan(self) -> None:
        planner = Planner(
            FakeResponsesClient(
                json.dumps(
                    {
                        "intent": "analyze",
                        "rationale": "need grounded analysis",
                        "steps": [
                            {"step_type": "retrieve", "label": "get evidence", "query": "pendulum", "limit": 6},
                            {"step_type": "execute_python", "label": "run analysis"},
                            {"step_type": "answer", "label": "answer"},
                        ],
                    }
                )
            ),
            "gpt-5",
        )
        plan = planner.build_plan(
            question="Why damping changes?",
            intent="analyze",
            targets=[],
            connect=True,
        )
        self.assertEqual([step.step_type for step in plan.steps], ["retrieve", "execute_python", "answer"])

    def test_default_plan_backwards_compatible(self) -> None:
        plan = default_plan("What is damping?", "retrieve")
        self.assertEqual(plan.steps[0].step_type, "retrieve")
        self.assertEqual(plan.steps[-1].step_type, "answer")

    def test_executor_runs_plan_and_generates_artifacts(self) -> None:
        workspace = self.base / "exec"
        build_csv_workspace(workspace)
        run_indexing(workspace, "workspace_exec", EventStreamHub())
        db_path = workspace / ".fieldnotes" / "fieldnotes.db"
        artifacts_dir = workspace / ".fieldnotes" / "artifacts"

        connection = connect_sqlite(db_path)
        try:
            provider = HybridProvider(connection, mode="hybrid", bm25_weight=0.5, vector_weight=0.5)
            plan = ExecutionPlan(
                intent="analyze",
                rationale="fixture",
                steps=[
                    PlanStep(step_type="retrieve", label="retrieve", query="damping explanation", limit=5),
                    PlanStep(step_type="analyze", label="analyze"),
                    PlanStep(step_type="execute_python", label="execute"),
                    PlanStep(step_type="calculate", label="calculate"),
                    PlanStep(step_type="summarize", label="summarize"),
                    PlanStep(step_type="answer", label="answer"),
                ],
            )
            context = Executor().execute(
                plan=plan,
                question="Why damping changes?",
                workspace_root=workspace,
                artifacts_dir=artifacts_dir,
                db_path=db_path,
                answer_id="answer_fixture",
                retrieval_provider=provider,
                llm_client=FakeExecutorLLM(),
            )
        finally:
            connection.close()

        self.assertTrue(context.retrieved_chunks)
        self.assertTrue(any(draft.artifact_type == "script" for draft in context.generated_artifacts))
        self.assertTrue(any(draft.artifact_type == "chart" for draft in context.generated_artifacts))
        self.assertTrue(any(draft.artifact_type == "analysis" for draft in context.generated_artifacts))
        self.assertTrue(any(draft.artifact_type == "table" for draft in context.generated_artifacts))
        self.assertIn("answer_context", context.intermediate_results)

    def test_executor_recovers_from_python_failure(self) -> None:
        workspace = self.base / "recover"
        build_csv_workspace(workspace)
        run_indexing(workspace, "workspace_recover", EventStreamHub())
        db_path = workspace / ".fieldnotes" / "fieldnotes.db"
        artifacts_dir = workspace / ".fieldnotes" / "artifacts"

        connection = connect_sqlite(db_path)
        try:
            provider = HybridProvider(connection, mode="hybrid", bm25_weight=0.5, vector_weight=0.5)
            plan = ExecutionPlan(
                intent="analyze",
                rationale="fixture",
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
                artifacts_dir=artifacts_dir,
                db_path=db_path,
                answer_id="answer_recover",
                retrieval_provider=provider,
                llm_client=FailingExecutorLLM(),
            )
        finally:
            connection.close()

        self.assertTrue(context.recovery_decisions)
        self.assertIn("continue_without_execute_python", context.recovery_decisions)

    def test_executor_failure_on_missing_retrieval(self) -> None:
        plan = ExecutionPlan(
            intent="retrieve",
            rationale="fixture",
            steps=[
                PlanStep(step_type="retrieve", label="retrieve", query="none", limit=5),
                PlanStep(step_type="answer", label="answer"),
            ],
        )
        with self.assertRaises(ValueError):
            Executor().execute(
                plan=plan,
                question="missing retrieval",
                workspace_root=self.base,
                artifacts_dir=self.base,
                db_path=self.base / "none.db",
                answer_id="answer_fail",
                retrieval_provider=type("Provider", (), {"search": lambda self, query, limit=5: (_ for _ in ()).throw(ValueError("broken retrieval"))})(),
                llm_client=FailingExecutorLLM(),
            )

    def test_citation_preservation_after_execution(self) -> None:
        workspace = self.base / "cite"
        build_csv_workspace(workspace)
        run_indexing(workspace, "workspace_cite", EventStreamHub())
        db_path = workspace / ".fieldnotes" / "fieldnotes.db"

        connection = connect_sqlite(db_path)
        try:
            provider = HybridProvider(connection, mode="hybrid", bm25_weight=0.5, vector_weight=0.5)
            chunks = provider.search("damping explanation", limit=5)
            chips = [
                type("Chip", (), {"anchor": f"{chunk.file_id}#{chunk.anchor}", "chip_type": "document", "label": chunk.relative_path})()
                for chunk in chunks
            ]
            valid = validate_citation_anchors(connection, chips)
        finally:
            connection.close()

        self.assertTrue(valid)

    def test_sandbox_rejects_disallowed_import(self) -> None:
        artifacts_dir = self.base / "artifacts"
        with self.assertRaisesRegex(RuntimeError, "Disallowed import"):
            run_generated_analysis(
                workspace_root=self.base,
                artifacts_dir=artifacts_dir,
                answer_id="answer_bad_import",
                script_source="import subprocess\n",
            )
        self.assertFalse((artifacts_dir / "answer_bad_import_analysis.py").exists())

    def test_sandbox_cleans_up_on_timeout(self) -> None:
        artifacts_dir = self.base / "artifacts"
        with self.assertRaisesRegex(RuntimeError, "timed out"):
            run_generated_analysis(
                workspace_root=self.base,
                artifacts_dir=artifacts_dir,
                answer_id="answer_timeout",
                script_source="import time\ntime.sleep(2)\n",
                timeout_seconds=1,
            )
        self.assertFalse((artifacts_dir / "answer_timeout_analysis.py").exists())
        self.assertFalse((artifacts_dir / "answer_timeout_result.json").exists())
        self.assertFalse((artifacts_dir / "answer_timeout_chart.png").exists())

    def test_execution_evaluation_metrics(self) -> None:
        metrics = evaluate_execution_cases(
            [
                ExecutionEvaluationCase(True, True, True, True),
                ExecutionEvaluationCase(True, False, True, False),
            ]
        )
        self.assertEqual(metrics.plan_completion_rate, 1.0)
        self.assertEqual(metrics.execution_success_rate, 0.5)
        self.assertEqual(metrics.citation_preservation_rate, 1.0)
        self.assertEqual(metrics.analysis_correctness, 0.5)


if __name__ == "__main__":
    unittest.main()
