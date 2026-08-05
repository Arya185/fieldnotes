"""Orchestrates specialized sub-agents to run a multi-step grounded plan.

The plan produced by `Planner`/`default_plan` is a flat list of typed steps
(retrieve, analyze, calculate, execute_python, summarize, answer). Rather than
one monolithic step-runner, each step is delegated to whichever sub-agent owns
that responsibility: `RetrievalAgent` (search the local index), `AnalysisAgent`
(dataset profiling + sandboxed code execution), or `SynthesisAgent` (combine
retrieval + analysis output into the grounded answer context). A "connect"
intent plan exercises all three in sequence; a plain "retrieve" plan only
exercises retrieval + synthesis.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from backend.agent.agents import AGENT_FOR_STEP_TYPE, AnalysisAgent, RetrievalAgent, SynthesisAgent
from backend.agent.execution_types import (
    AnalysisStepOutput,
    AnswerStepOutput,
    CalculationStepOutput,
    ExecutionArtifactDraft,
    ExecutionContext,
    PythonExecutionOutput,
    RetrievalStepOutput,
    StepExecution,
    SummaryStepOutput,
)
from backend.agent.planner import ExecutionPlan, PlanStep
from backend.indexer.bm25 import RetrievalProvider
from backend.telemetry.tracing import metrics_registry, trace_collector

__all__ = [
    "Executor",
    "ExecutionContext",
    "StepExecution",
    "ExecutionArtifactDraft",
    "RetrievalStepOutput",
    "AnalysisStepOutput",
    "CalculationStepOutput",
    "PythonExecutionOutput",
    "SummaryStepOutput",
    "AnswerStepOutput",
]


class Executor:
    """Orchestrate the retrieval, analysis, and synthesis sub-agents over one plan."""

    def __init__(self) -> None:
        self.retrieval_agent = RetrievalAgent()
        self.analysis_agent = AnalysisAgent()
        self.synthesis_agent = SynthesisAgent()

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
                agent_name = AGENT_FOR_STEP_TYPE.get(step.step_type, "")
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
                            agent=agent_name,
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
                                agent=agent_name,
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
                            agent=agent_name,
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
            return self.retrieval_agent.run(
                step=step,
                question=question,
                retrieval_provider=retrieval_provider,
                context=context,
            )
        if step.step_type == "analyze":
            return self.analysis_agent.analyze(db_path, context)
        if step.step_type == "calculate":
            return self.analysis_agent.calculate(context)
        if step.step_type == "execute_python":
            return self.analysis_agent.execute_python(
                question=question,
                workspace_root=workspace_root,
                artifacts_dir=artifacts_dir,
                answer_id=answer_id,
                llm_client=llm_client,
                context=context,
            )
        if step.step_type == "summarize":
            return self.synthesis_agent.summarize(context)
        if step.step_type == "answer":
            return self.synthesis_agent.answer(question, context)
        raise ValueError(f"Unsupported step type: {step.step_type}")

    def _recovery_for_step(self, step: PlanStep) -> str | None:
        if step.step_type in {"analyze", "calculate", "execute_python", "summarize"}:
            return f"continue_without_{step.step_type}"
        return None
