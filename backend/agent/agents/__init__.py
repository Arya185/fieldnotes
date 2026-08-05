"""Specialized sub-agents that the orchestrating Executor dispatches plan steps to."""

from __future__ import annotations

from backend.agent.agents.analysis_agent import AnalysisAgent
from backend.agent.agents.retrieval_agent import RetrievalAgent
from backend.agent.agents.synthesis_agent import SynthesisAgent

AGENT_FOR_STEP_TYPE: dict[str, str] = {
    "retrieve": RetrievalAgent.name,
    "analyze": AnalysisAgent.name,
    "calculate": AnalysisAgent.name,
    "execute_python": AnalysisAgent.name,
    "summarize": SynthesisAgent.name,
    "answer": SynthesisAgent.name,
}

__all__ = ["RetrievalAgent", "AnalysisAgent", "SynthesisAgent", "AGENT_FOR_STEP_TYPE"]
