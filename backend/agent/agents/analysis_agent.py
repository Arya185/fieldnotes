"""Analysis sub-agent: local dataset profiling and sandboxed code execution."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.agent.execution_types import (
    AnalysisStepOutput,
    CalculationStepOutput,
    ExecutionArtifactDraft,
    ExecutionContext,
    PythonExecutionOutput,
)
from backend.sandbox.runner import run_generated_analysis
from backend.storage import load_dataset_profiles


class AnalysisAgent:
    """Owns `analyze`, `calculate`, and `execute_python` plan steps."""

    name = "analysis-agent"

    def analyze(self, db_path: Path, context: ExecutionContext) -> AnalysisStepOutput:
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

    def calculate(self, context: ExecutionContext) -> CalculationStepOutput:
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

    def execute_python(
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


def _table_payload_from_result(result_payload: dict[str, Any]) -> str | None:
    metrics = result_payload.get("metrics")
    if not isinstance(metrics, dict) or not metrics:
        return None
    lines = ["key\tvalue"]
    for key, value in metrics.items():
        lines.append(f"{key}\t{json.dumps(value, sort_keys=True)}")
    return "\n".join(lines)
