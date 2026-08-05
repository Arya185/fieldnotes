"""Retrieval sub-agent: resolves grounded passages for one plan step."""

from __future__ import annotations

from backend.agent.execution_types import ExecutionContext, RetrievalStepOutput
from backend.agent.planner import PlanStep
from backend.indexer.bm25 import RetrievalProvider


class RetrievalAgent:
    """Owns the `retrieve` plan step: searches the local index for grounded passages."""

    name = "retrieval-agent"

    def run(
        self,
        *,
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
