"""Synthesis sub-agent: reconciles retrieval and analysis output into one grounded context."""

from __future__ import annotations

import json

from backend.agent.execution_types import AnswerStepOutput, ExecutionContext, SummaryStepOutput


class SynthesisAgent:
    """Owns `summarize` and `answer` plan steps.

    For "connect"-style questions this is the step that reconciles what the
    retrieval agent found with what the analysis agent computed, before the
    grounded answer is streamed back to the user.
    """

    name = "synthesis-agent"

    def summarize(self, context: ExecutionContext) -> SummaryStepOutput:
        if "python_result" in context.intermediate_results:
            payload = context.intermediate_results["python_result"]
            summary = payload.get("summary", "analysis complete") if isinstance(payload, dict) else str(payload)
        elif "calculation" in context.intermediate_results:
            summary = json.dumps(context.intermediate_results["calculation"], sort_keys=True)
        else:
            summary = f"{len(context.retrieved_chunks)} grounded chunks retrieved"
        context.intermediate_results["summary"] = summary
        return SummaryStepOutput(text=summary)

    def answer(self, question: str, context: ExecutionContext) -> AnswerStepOutput:
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
