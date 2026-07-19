"""Sequential executor for multi-step grounded plans."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.agent.planner import ExecutionPlan, PlanStep
from backend.indexer.bm25 import RetrievalChunk, RetrievalProvider
from backend.models import DatasetProfile
from backend.sandbox.runner import SandboxResult, run_generated_analysis
from backend.storage import load_dataset_profiles
from backend.telemetry.tracing import metrics_registry, trace_collector


@dataclass(frozen=True)
class RetrievalStepOutput:
    chunks: list[RetrievalChunk]


@dataclass(frozen=True)
class AnalysisStepOutput:
    dataset_profiles: list[DatasetProfile]
    dataset_profiles_json: str


@dataclass(frozen=True)
class CalculationStepOutput:
    values: dict[str, Any]


@dataclass(frozen=True)
class PythonExecutionOutput:
    sandbox_result: SandboxResult
    structured_result: dict[str, Any]


@dataclass(frozen=True)
class SummaryStepOutput:
    text: str


@dataclass(frozen=True)
class AnswerStepOutput:
    execution_context: str


@dataclass(frozen=True)
class StepExecution:
    step_type: str
    label: str
    status: str
    duration_ms: int
    output: Any = None
    error: str | None = None
    recovery: str | None = None


@dataclass(frozen=True)
class ExecutionArtifactDraft:
    artifact_type: str
    persisted_kind: str
    title: str
    payload_text: str | None = None
    file_extension: str | None = None
    existing_file_path: Path | None = None
    emit_event_kind: str | None = None


@dataclass
class ExecutionContext:
    plan: ExecutionPlan
    retrieved_chunks: list[RetrievalChunk] = field(default_factory=list)
    intermediate_results: dict[str, Any] = field(default_factory=dict)
    generated_artifacts: list[ExecutionArtifactDraft] = field(default_factory=list)
    execution_logs: list[str] = field(default_factory=list)
    step_executions: list[StepExecution] = field(default_factory=list)
    tool_usage: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    recovery_decisions: list[str] = field(default_factory=list)


class Executor:
    """Run execution plan sequentially."""

    def execute(
        self,
        *,
        plan: ExecutionPlan,
        question: str,
        workspace_root: Path,
        artifacts_dir: Path,
        db_path: Path,
        answer_id: str,
        retrieval_provider: RetrievalProvider,
        llm_client,
    ) -> ExecutionContext:
        context = ExecutionContext(plan=plan)
        executor_started = time.perf_counter()
        with trace_collector.span("execution", step_count=len(plan.steps), intent=plan.intent):
            for step in plan.steps:
                started = time.perf_counter()
                try:
                    output = self._run_step(
                        step=step,
                        question=question,
                        workspace_root=workspace_root,
                        artifacts_dir=artifacts_dir,
                        db_path=db_path,
                        answer_id=answer_id,
                        retrieval_provider=retrieval_provider,
                        llm_client=llm_client,
                        context=context,
                    )
                    context.step_executions.append(
                        StepExecution(
                            step_type=step.step_type,
                            label=step.label,
                            status="ok",
                            duration_ms=int((time.perf_counter() - started) * 1000),
                            output=output,
                        )
                    )
                except Exception as exc:
                    recovery = self._recovery_for_step(step)
                    context.failures.append(f"{step.step_type}: {exc}")
                    if recovery is None:
                        context.step_executions.append(
                            StepExecution(
                                step_type=step.step_type,
                                label=step.label,
                                status="failed",
                                duration_ms=int((time.perf_counter() - started) * 1000),
                                error=str(exc),
                            )
                        )
                        raise
                    context.recovery_decisions.append(recovery)
                    context.execution_logs.append(recovery)
                    context.step_executions.append(
                        StepExecution(
                            step_type=step.step_type,
                            label=step.label,
                            status="failed",
                            duration_ms=int((time.perf_counter() - started) * 1000),
                            error=str(exc),
                            recovery=recovery,
                        )
                    )
        metrics_registry.record("executor_latency_ms", (time.perf_counter() - executor_started) * 1000)
        return context

    def _run_step(
        self,
        *,
        step: PlanStep,
        question: str,
        workspace_root: Path,
        artifacts_dir: Path,
        db_path: Path,
        answer_id: str,
        retrieval_provider: RetrievalProvider,
        llm_client,
        context: ExecutionContext,
    ) -> Any:
        if step.step_type == "retrieve":
            return self._retrieve(step, question, retrieval_provider, context)
        if step.step_type == "analyze":
            return self._analyze(db_path, context)
        if step.step_type == "calculate":
            return self._calculate(context)
        if step.step_type == "execute_python":
            return self._execute_python(
                question=question,
                workspace_root=workspace_root,
                artifacts_dir=artifacts_dir,
                answer_id=answer_id,
                llm_client=llm_client,
                context=context,
            )
        if step.step_type == "summarize":
            return self._summarize(context)
        if step.step_type == "answer":
            return self._answer(question, context)
        raise ValueError(f"Unsupported step type: {step.step_type}")

    def _retrieve(
        self,
        step: PlanStep,
        question: str,
        retrieval_provider: RetrievalProvider,
        context: ExecutionContext,
    ) -> RetrievalStepOutput:
        query = step.query or question
        limit = step.limit or 5
        chunks = retrieval_provider.search(query, limit=limit)
        context.retrieved_chunks = chunks
        context.intermediate_results["retrieval_query"] = query
        context.intermediate_results["retrieval_limit"] = limit
        context.tool_usage.append("retrieval_provider.search")
        return RetrievalStepOutput(chunks=chunks)

    def _analyze(self, db_path: Path, context: ExecutionContext) -> AnalysisStepOutput:
        from backend.db import connect_sqlite

        connection = connect_sqlite(db_path)
        try:
            dataset_profiles = load_dataset_profiles(connection)
        finally:
            connection.close()
        payload = json.dumps([profile.model_dump() for profile in dataset_profiles])
        context.intermediate_results["dataset_profiles"] = payload
        return AnalysisStepOutput(
            dataset_profiles=dataset_profiles,
            dataset_profiles_json=payload,
        )

    def _calculate(self, context: ExecutionContext) -> CalculationStepOutput:
        if "python_result" in context.intermediate_results:
            structured = context.intermediate_results["python_result"]
            metrics = structured.get("metrics", {}) if isinstance(structured, dict) else {}
            values = {key: value for key, value in metrics.items() if isinstance(value, (int, float, str, list, dict))}
        elif "dataset_profiles" in context.intermediate_results:
            profiles = json.loads(context.intermediate_results["dataset_profiles"])
            values = {"dataset_count": len(profiles)}
        else:
            raise ValueError("No intermediate results available for calculation")
        context.intermediate_results["calculation"] = values
        return CalculationStepOutput(values=values)

    def _execute_python(
        self,
        *,
        question: str,
        workspace_root: Path,
        artifacts_dir: Path,
        answer_id: str,
        llm_client,
        context: ExecutionContext,
    ) -> PythonExecutionOutput:
        dataset_profiles_json = context.intermediate_results.get("dataset_profiles")
        if not dataset_profiles_json:
            raise ValueError("No dataset profiles available for python execution")
        analysis_plan = llm_client.generate_analysis_script(
            question=question,
            retrieval_results=context.retrieved_chunks,
            dataset_profiles_json=dataset_profiles_json,
        )
        context.tool_usage.append("llm.generate_analysis_script")
        sandbox_result = run_generated_analysis(
            workspace_root=workspace_root,
            artifacts_dir=artifacts_dir,
            answer_id=answer_id,
            script_source=analysis_plan.script,
        )
        context.tool_usage.append("sandbox.run_generated_analysis")
        context.intermediate_results["python_result"] = sandbox_result.result_payload
        context.execution_logs.append(sandbox_result.stdout.strip())
        context.generated_artifacts.append(
            ExecutionArtifactDraft(
                artifact_type="script",
                persisted_kind="script",
                title=analysis_plan.title,
                payload_text=sandbox_result.stdout or None,
                existing_file_path=sandbox_result.script_path,
                emit_event_kind="script",
            )
        )
        if sandbox_result.chart_path.exists():
            context.generated_artifacts.append(
                ExecutionArtifactDraft(
                    artifact_type="chart",
                    persisted_kind="chart",
                    title=f"{analysis_plan.title} chart",
                    existing_file_path=sandbox_result.chart_path,
                    emit_event_kind="chart",
                )
            )
        context.generated_artifacts.append(
            ExecutionArtifactDraft(
                artifact_type="analysis",
                persisted_kind="explainer",
                title=f"Analysis: {analysis_plan.title}",
                payload_text=json.dumps(sandbox_result.result_payload, indent=2, sort_keys=True),
            )
        )
        table_payload = _table_payload_from_result(sandbox_result.result_payload)
        if table_payload is not None:
            context.generated_artifacts.append(
                ExecutionArtifactDraft(
                    artifact_type="table",
                    persisted_kind="explainer",
                    title=f"Table: {analysis_plan.title}",
                    payload_text=table_payload,
                )
            )
        return PythonExecutionOutput(
            sandbox_result=sandbox_result,
            structured_result=sandbox_result.result_payload,
        )

    def _summarize(self, context: ExecutionContext) -> SummaryStepOutput:
        if "python_result" in context.intermediate_results:
            payload = context.intermediate_results["python_result"]
            summary = payload.get("summary", "analysis complete") if isinstance(payload, dict) else str(payload)
        elif "calculation" in context.intermediate_results:
            summary = json.dumps(context.intermediate_results["calculation"], sort_keys=True)
        else:
            summary = f"{len(context.retrieved_chunks)} grounded chunks retrieved"
        context.intermediate_results["summary"] = summary
        return SummaryStepOutput(text=summary)

    def _answer(self, question: str, context: ExecutionContext) -> AnswerStepOutput:
        payload = {
            "question": question,
            "summary": context.intermediate_results.get("summary"),
            "calculation": context.intermediate_results.get("calculation"),
            "python_result": context.intermediate_results.get("python_result"),
            "logs": [log for log in context.execution_logs if log],
        }
        execution_context = json.dumps(payload)
        context.intermediate_results["answer_context"] = execution_context
        return AnswerStepOutput(execution_context=execution_context)

    def _recovery_for_step(self, step: PlanStep) -> str | None:
        if step.step_type in {"analyze", "calculate", "execute_python", "summarize"}:
            return f"continue_without_{step.step_type}"
        return None


def _table_payload_from_result(result_payload: dict[str, Any]) -> str | None:
    metrics = result_payload.get("metrics")
    if not isinstance(metrics, dict) or not metrics:
        return None
    lines = ["key\tvalue"]
    for key, value in metrics.items():
        lines.append(f"{key}\t{json.dumps(value, sort_keys=True)}")
    return "\n".join(lines)
