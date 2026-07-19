"""Structured planner for multi-step grounded execution."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.telemetry.tracing import metrics_registry, trace_collector


PlanStepType = Literal[
    "retrieve",
    "analyze",
    "summarize",
    "calculate",
    "execute_python",
    "answer",
]


class PlanStep(BaseModel):
    """One typed execution step."""

    model_config = ConfigDict(extra="forbid")

    step_type: PlanStepType
    label: str
    query: str | None = None
    limit: int | None = Field(default=None, ge=1, le=12)


class ExecutionPlan(BaseModel):
    """Typed execution plan returned by planner."""

    model_config = ConfigDict(extra="forbid")

    intent: str
    rationale: str
    steps: list[PlanStep] = Field(min_length=2)


class Planner:
    """Use Responses API structured outputs to plan execution."""

    def __init__(self, client, model: str) -> None:
        self.client = client
        self.model = model

    def build_plan(
        self,
        *,
        question: str,
        intent: str,
        targets: list[str],
        connect: bool,
    ) -> ExecutionPlan:
        with trace_collector.span("planning", question=question, intent=intent, targets=targets) as metadata:
            import time

            started = time.perf_counter()
            response = self.client.responses.create(
                model=self.model,
                store=False,
                input=[
                    {
                        "role": "developer",
                        "content": (
                            "Create deterministic execution plan for grounded local reasoning. "
                            "Allowed steps only: retrieve, analyze, summarize, calculate, execute_python, answer. "
                            "Plan must end with answer. Use execute_python only when local data analysis is needed. "
                            "Use calculate for deterministic metric extraction from prior results. "
                            "Use summarize when intermediate results should be compressed before final answer."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"Question: {question}\n"
                            f"Intent: {intent}\n"
                            f"Targets: {targets}\n"
                            f"Connect: {connect}"
                        ),
                    },
                ],
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "execution_plan",
                        "schema": ExecutionPlan.model_json_schema(),
                        "strict": True,
                    }
                },
            )
            metrics_registry.record("planner_latency_ms", (time.perf_counter() - started) * 1000)
            plan = ExecutionPlan.model_validate_json(response.output_text)
            metadata["step_types"] = [step.step_type for step in plan.steps]
            if plan.steps[-1].step_type != "answer":
                raise ValueError("Execution plan must end with answer")
            return plan


def default_plan(question: str, intent: str) -> ExecutionPlan:
    """Local fallback plan when planner unavailable."""

    lowered = question.lower()
    needs_calculation = any(token in lowered for token in ("mean", "average", "sum", "count", "total"))
    steps = [
        PlanStep(step_type="retrieve", label="retrieve grounded context", query=question, limit=8),
    ]
    if intent in {"analyze", "visualize", "connect"}:
        steps.append(PlanStep(step_type="analyze", label="prepare local analysis"))
        steps.append(PlanStep(step_type="execute_python", label="run local analysis script"))
        if needs_calculation:
            steps.append(PlanStep(step_type="calculate", label="derive key calculations"))
        steps.append(PlanStep(step_type="summarize", label="summarize execution results"))
    elif needs_calculation:
        steps.append(PlanStep(step_type="calculate", label="derive grounded calculation"))
        steps.append(PlanStep(step_type="summarize", label="summarize calculation"))

    steps.append(PlanStep(step_type="answer", label="answer with grounded evidence"))
    return ExecutionPlan(
        intent=intent,
        rationale="fallback deterministic plan",
        steps=steps,
    )
