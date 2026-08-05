"""Shared data shapes passed between the retrieval, analysis, and synthesis sub-agents."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.agent.planner import ExecutionPlan
from backend.indexer.bm25 import RetrievalChunk
from backend.models import DatasetProfile
from backend.sandbox.runner import SandboxResult


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
    agent: str = ""


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
