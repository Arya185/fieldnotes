"""OpenAI Responses API integration isolated from transport and storage."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Iterator

from openai import APITimeoutError, AuthenticationError, OpenAI
from pydantic import BaseModel, ConfigDict, Field

from backend.agent.executor import ExecutionContext, Executor
from backend.agent.planner import ExecutionPlan, Planner, default_plan
from backend.config import (
    DEFAULT_OPENAI_TIMEOUT_SECONDS,
    OPENAI_BASE_URL,
    OPENAI_MODEL,
    env_value,
    validate_positive_float,
)
from backend.indexer.bm25 import RetrievalChunk, RetrievalProvider
from backend.indexer.reranker import DeterministicReranker
from backend.models import ArtifactEvent, ConceptUpdate, QuizQuestionSchema, RouteIntentSchema
from backend.release import FakeLLMClient as FakeLLMClient
from backend.telemetry.tracing import metrics_registry, trace_collector


SEARCH_INDEX_TOOL = {
    "type": "function",
    "name": "search_index",
    "description": "Search persisted local course chunks and return the most relevant anchored passages.",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 8},
        },
        "required": ["query", "limit"],
        "additionalProperties": False,
    },
    "strict": True,
}


class AnalysisScriptSchema(BaseModel):
    """Structured output for local analysis code generation."""

    model_config = ConfigDict(extra="forbid")

    target_file_path: str
    title: str
    needs_chart: bool
    script: str


class ConceptCandidateSchema(BaseModel):
    """Structured grounded concept candidate."""

    model_config = ConfigDict(extra="forbid")

    name: str
    source_anchor: str


class ConceptExtractionSchema(BaseModel):
    """Structured output for grounded concept extraction."""

    model_config = ConfigDict(extra="forbid")

    concepts: list[ConceptCandidateSchema] = Field(default_factory=list, max_length=3)


@dataclass(frozen=True)
class ResponsesAPIProbeResult:
    model: str
    output_text: str
    response_id: str | None


class ResponsesAPIProbeError(RuntimeError):
    """Raised when live Responses API verification fails."""


def verify_responses_api_connection(
    *,
    model: str,
    api_key: str | None = None,
    base_url: str | None = None,
    timeout_seconds: float = 10.0,
    client: OpenAI | None = None,
) -> ResponsesAPIProbeResult:
    """Run minimal live Responses API probe through shipped OpenAI client wrapper."""

    normalized_model = model.strip()
    if not normalized_model:
        raise ResponsesAPIProbeError("OPENAI_MODEL must not be empty")

    wrapper = LLMClient(
        model=normalized_model,
        timeout_seconds=timeout_seconds,
        api_key=api_key,
        base_url=base_url,
        client=client,
        max_retries=0,
    )

    try:
        response = wrapper._create_structured_completion(
            response_name="live_probe",
            schema={
                "type": "object",
                "properties": {
                    "status": {"type": "string"},
                },
                "required": ["status"],
                "additionalProperties": False,
            },
            input_items=[
                {
                    "role": "developer",
                    "content": "Return JSON only. Reply with {\"status\":\"ok\"}.",
                },
                {
                    "role": "user",
                    "content": "ping",
                },
            ],
        )
    except AuthenticationError as exc:
        raise ResponsesAPIProbeError("OpenAI authentication failed. Check OPENAI_API_KEY.") from exc
    except APITimeoutError as exc:
        raise ResponsesAPIProbeError(
            f"OpenAI Responses API probe timed out after {timeout_seconds}s. Increase timeout or retry."
        ) from exc
    except Exception as exc:
        raise ResponsesAPIProbeError(f"OpenAI Responses API probe failed: {exc}") from exc

    output_text = wrapper._response_output_text(response)
    if not output_text.strip():
        raise ResponsesAPIProbeError("OpenAI Responses API probe returned empty output")

    try:
        payload = json.loads(output_text)
    except json.JSONDecodeError as exc:
        raise ResponsesAPIProbeError("OpenAI Responses API probe returned invalid JSON") from exc

    if payload.get("status") != "ok":
        raise ResponsesAPIProbeError(f"OpenAI Responses API probe returned unexpected payload: {payload}")

    return ResponsesAPIProbeResult(
        model=normalized_model,
        output_text=output_text,
        response_id=getattr(response, "id", None),
    )


class LLMClient:
    """Thin wrapper around OpenAI Responses API."""

    def __init__(
        self,
        model: str = OPENAI_MODEL,
        *,
        timeout_seconds: float | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        client: OpenAI | None = None,
        max_retries: int = 1,
    ) -> None:
        normalized_base_url = (base_url or OPENAI_BASE_URL or "").strip()
        effective_timeout_seconds = (
            timeout_seconds
            if timeout_seconds is not None
            else validate_positive_float(
                "FIELDNOTES_OPENAI_TIMEOUT_SECONDS",
                env_value("FIELDNOTES_OPENAI_TIMEOUT_SECONDS", DEFAULT_OPENAI_TIMEOUT_SECONDS),
            )
        )
        self.client = client or OpenAI(
            api_key=api_key,
            timeout=effective_timeout_seconds,
            max_retries=max_retries,
            base_url=normalized_base_url or None,
        )
        self.model = model
        self.base_url = normalized_base_url
        self.timeout_seconds = effective_timeout_seconds
        self.use_chat_completions_compat = bool(normalized_base_url)
        self.reranker = DeterministicReranker()
        self.planner = Planner(self.client, self.model)
        self.executor = Executor()

    def _to_chat_messages(self, input_items: list[dict[str, str]]) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = []
        for item in input_items:
            role = item["role"]
            if role == "developer":
                role = "system"
            messages.append({"role": role, "content": item["content"]})
        return messages

    def _create_structured_completion(
        self,
        *,
        response_name: str,
        schema: dict[str, Any],
        input_items: list[dict[str, str]],
        max_output_tokens: int | None = None,
    ):
        if not self.use_chat_completions_compat:
            return self.client.responses.create(
                model=self.model,
                store=False,
                input=input_items,
                max_output_tokens=max_output_tokens,
                text={
                    "format": {
                        "type": "json_schema",
                        "name": response_name,
                        "schema": schema,
                        "strict": True,
                    }
                },
            )

        request: dict[str, Any] = {
            "model": self.model,
            "messages": self._to_chat_messages(input_items),
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": response_name,
                    "schema": schema,
                    "strict": True,
                },
            },
        }
        if max_output_tokens is not None:
            request["max_tokens"] = max_output_tokens
        return self.client.chat.completions.create(**request)

    def _create_tool_completion(
        self,
        *,
        input_items: list[dict[str, str]],
        tools: list[dict[str, Any]],
    ):
        if not self.use_chat_completions_compat:
            return self.client.responses.create(
                model=self.model,
                store=False,
                input=input_items,
                tools=tools,
            )

        chat_tools = [
            {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "parameters": tool.get("parameters", {}),
                    "strict": tool.get("strict", False),
                },
            }
            for tool in tools
        ]
        return self.client.chat.completions.create(
            model=self.model,
            messages=self._to_chat_messages(input_items),
            tools=chat_tools,
        )

    def _response_output_text(self, response) -> str:
        if not self.use_chat_completions_compat:
            return getattr(response, "output_text", "") or ""
        choice = (getattr(response, "choices", None) or [None])[0]
        message = getattr(choice, "message", None)
        content = getattr(message, "content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                text = getattr(item, "text", None)
                if text:
                    parts.append(text)
                elif isinstance(item, dict) and item.get("text"):
                    parts.append(str(item["text"]))
            return "".join(parts)
        return ""

    def _iter_tool_calls(self, response) -> Iterator[dict[str, str]]:
        if not self.use_chat_completions_compat:
            yield from _iter_function_calls(response)
            return

        choice = (getattr(response, "choices", None) or [None])[0]
        message = getattr(choice, "message", None)
        for tool_call in getattr(message, "tool_calls", None) or []:
            function = getattr(tool_call, "function", None)
            yield {
                "call_id": getattr(tool_call, "id", ""),
                "name": getattr(function, "name", ""),
                "arguments": getattr(function, "arguments", "{}"),
            }

    def classify_intent(self, question: str) -> RouteIntentSchema:
        """Classify user question with structured outputs."""

        import time

        with trace_collector.span("responses_api", operation="classify_intent") as metadata:
            started = time.perf_counter()
            response = self._create_structured_completion(
                response_name="route_intent",
                schema=RouteIntentSchema.model_json_schema(),
                input_items=[
                    {
                        "role": "developer",
                        "content": (
                            "Classify the user's question into exactly one intent from the schema. "
                            "Use empty targets when the question names no file."
                        ),
                    },
                    {"role": "user", "content": question},
                ],
            )
            metrics_registry.record("llm_latency_ms", (time.perf_counter() - started) * 1000)
            result = RouteIntentSchema.model_validate_json(self._response_output_text(response))
            metadata["intent"] = result.intent
            return result

    def resolve_retrieval(
        self, question: str, retrieval_provider: RetrievalProvider
    ) -> list[RetrievalChunk]:
        """Use flat Responses API tool definitions, then execute local retrieval."""
        import time

        with trace_collector.span("responses_api", operation="resolve_retrieval") as metadata:
            started = time.perf_counter()
            response = self._create_tool_completion(
                input_items=[
                    {
                        "role": "developer",
                        "content": (
                            "Use the search_index function to retrieve grounded passages for the user's question. "
                            "Choose a short focused query and a limit between 3 and 8."
                        ),
                    },
                    {"role": "user", "content": question},
                ],
                tools=[SEARCH_INDEX_TOOL],
            )
            metrics_registry.record("llm_latency_ms", (time.perf_counter() - started) * 1000)
            metadata["question"] = question

            tool_calls = list(self._iter_tool_calls(response))
            if not tool_calls:
                candidate_results = retrieval_provider.search(
                    question,
                    limit=self.reranker.max_retrieval_candidates or 5,
                )
                return self.reranker.rerank(question, candidate_results, limit=5).selected_chunks

            latest_results: list[RetrievalChunk] = []
            for tool_call in tool_calls:
                arguments = json.loads(tool_call["arguments"])
                query = arguments.get("query", question)
                limit = int(arguments.get("limit", 5))
                candidate_results = retrieval_provider.search(
                    query,
                    limit=max(limit, self.reranker.max_retrieval_candidates or limit),
                )
                latest_results = self.reranker.rerank(
                    query,
                    candidate_results,
                    limit=limit,
                ).selected_chunks
            if latest_results and not self.use_chat_completions_compat:
                tool_outputs = [
                    {
                        "type": "function_call_output",
                        "call_id": tool_call["call_id"],
                        "output": json.dumps(
                            [
                                {
                                    "chunk": result.chunk,
                                    "score": result.score,
                                    "anchor": result.anchor,
                                    "file_id": result.file_id,
                                    "relative_path": result.relative_path,
                                }
                                for result in latest_results
                            ]
                        ),
                    }
                    for tool_call in tool_calls
                ]
                started = time.perf_counter()
                self.client.responses.create(
                    model=self.model,
                    store=False,
                    previous_response_id=response.id,
                    input=tool_outputs,
                )
                metrics_registry.record("llm_latency_ms", (time.perf_counter() - started) * 1000)

            return latest_results

    def build_plan(self, question: str, intent_result: RouteIntentSchema) -> ExecutionPlan:
        """Build typed execution plan for ask pipeline."""

        try:
            return self.planner.build_plan(
                question=question,
                intent=intent_result.intent,
                targets=intent_result.targets,
                connect=intent_result.connect,
            )
        except Exception:
            return default_plan(question, intent_result.intent)

    def execute_plan(
        self,
        *,
        plan: ExecutionPlan,
        question: str,
        workspace_root,
        artifacts_dir,
        db_path,
        answer_id: str,
        retrieval_provider: RetrievalProvider,
    ) -> ExecutionContext:
        """Execute plan sequentially with local tools."""

        return self.executor.execute(
            plan=plan,
            question=question,
            workspace_root=workspace_root,
            artifacts_dir=artifacts_dir,
            db_path=db_path,
            answer_id=answer_id,
            retrieval_provider=retrieval_provider,
            llm_client=self,
        )

    def stream_grounded_answer(
        self,
        question: str,
        intent: str,
        retrieval_results: list[RetrievalChunk],
        execution_context: str | None = None,
    ) -> Iterator[str]:
        """Stream grounded answer text from retrieved chunks."""

        context = "\n\n".join(
            [
                f"[{index}] file_id={result.file_id} anchor={result.anchor}\n{result.chunk}"
                .replace(f"file_id={result.file_id}", f"path={result.relative_path}")
                for index, result in enumerate(retrieval_results, start=1)
            ]
        )
        input_items = [
            {
                "role": "developer",
                "content": (
                    "Answer the user's question using only the provided retrieved passages. "
                    "Use execution results when provided. "
                    "Do not invent citations. If evidence is insufficient, say so plainly. "
                    f"The routed intent is {intent}."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Question:\n{question}\n\nRetrieved passages:\n{context}\n\n"
                    f"Execution context:\n{execution_context or 'None'}"
                ),
            },
        ]
        if not self.use_chat_completions_compat:
            stream = self.client.responses.create(
                model=self.model,
                store=False,
                stream=True,
                input=input_items,
            )

            for event in stream:
                event_type = getattr(event, "type", None)
                if event_type == "response.output_text.delta":
                    yield getattr(event, "delta", "")
            return

        stream = self.client.chat.completions.create(
            model=self.model,
            messages=self._to_chat_messages(input_items),
            stream=True,
        )
        for chunk in stream:
            choice = (getattr(chunk, "choices", None) or [None])[0]
            delta = getattr(choice, "delta", None)
            text = getattr(delta, "content", None)
            if text:
                yield text

    def generate_analysis_script(
        self,
        *,
        question: str,
        retrieval_results: list[RetrievalChunk],
        dataset_profiles_json: str,
    ) -> AnalysisScriptSchema:
        """Generate local Python analysis script against persisted dataset schema."""

        passages = "\n\n".join(
            [
                f"[{index}] path={result.relative_path} anchor={result.file_id}#{result.anchor}\n{result.chunk}"
                for index, result in enumerate(retrieval_results, start=1)
            ]
        )
        response = self._create_structured_completion(
            response_name="analysis_script",
            schema=AnalysisScriptSchema.model_json_schema(),
            input_items=[
                {
                    "role": "developer",
                    "content": (
                        "Write one local Python analysis script for workspace data. "
                        "Return JSON only. target_file_path must match one provided DatasetProfile file_path exactly. "
                        "Script must read target_file_path with pandas from workspace-relative path only. "
                        "Script must call write_result({'summary': <string>, 'metrics': <object>}). "
                        "If chart useful, call save_chart() or write_chart_bytes(...). "
                        "Available modules: pandas, numpy, matplotlib.pyplot, json, math, statistics, re, csv, collections, datetime, typing. "
                        "Do not use os, pathlib, open, subprocess, sockets, imports outside allowed list, or absolute paths."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Question:\n{question}\n\nRetrieved passages:\n{passages}\n\n"
                        f"Dataset profiles:\n{dataset_profiles_json}"
                    ),
                },
            ],
        )
        return AnalysisScriptSchema.model_validate_json(self._response_output_text(response))

    def generate_quiz_question(
        self,
        retrieval_results: list[RetrievalChunk],
        concept_ids: list[str] | None = None,
    ) -> QuizQuestionSchema:
        """Generate one grounded quiz question from retrieved chunks."""

        context = "\n\n".join(
            [
                f"[{index}] path={result.relative_path} anchor={result.file_id}#{result.anchor}\n{result.chunk}"
                for index, result in enumerate(retrieval_results, start=1)
            ]
        )
        concept_hint = (
            f"Prefer these concept IDs when relevant: {', '.join(concept_ids)}."
            if concept_ids
            else "Choose a concrete concept directly supported by the retrieved passages."
        )
        response = self._create_structured_completion(
            response_name="quiz_question",
            schema=QuizQuestionSchema.model_json_schema(),
            input_items=[
                {
                    "role": "developer",
                    "content": (
                        "Generate exactly one multiple-choice quiz question grounded only in the "
                        "retrieved passages. Use exactly four options, exactly one correct answer, "
                        "and return the source_anchor as one of the provided full anchors. "
                        f"{concept_hint}"
                    ),
                },
                {
                    "role": "user",
                    "content": f"Retrieved passages:\n{context}",
                },
            ],
        )
        return QuizQuestionSchema.model_validate_json(self._response_output_text(response))

    def extract_concepts(
        self,
        question: str,
        retrieval_results: list[RetrievalChunk],
    ) -> list[ConceptUpdate]:
        """Derive grounded concept updates from retrieved passages."""

        if not retrieval_results:
            return []

        context = "\n\n".join(
            [
                f"[{index}] path={result.relative_path} source_anchor={result.file_id}#{result.anchor}\n{result.chunk}"
                for index, result in enumerate(retrieval_results, start=1)
            ]
        )
        response = self._create_structured_completion(
            response_name="concept_extraction",
            schema=ConceptExtractionSchema.model_json_schema(),
            max_output_tokens=180,
            input_items=[
                {
                    "role": "developer",
                    "content": (
                        "Extract up to 3 short grounded concept names from retrieved passages only. "
                        "Each concept must use exactly one provided source_anchor. "
                        "Return no concept if support is weak."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Question:\n{question}\n\nRetrieved passages:\n{context}",
                },
            ],
        )
        extracted = ConceptExtractionSchema.model_validate_json(self._response_output_text(response))
        valid_anchors = {f"{result.file_id}#{result.anchor}" for result in retrieval_results}
        updates: list[ConceptUpdate] = []
        seen_names: set[str] = set()
        for concept in extracted.concepts:
            normalized_name = concept.name.strip().lower()
            if not normalized_name or normalized_name in seen_names:
                continue
            if concept.source_anchor not in valid_anchors:
                continue
            seen_names.add(normalized_name)
            updates.append(
                ConceptUpdate(
                    concept_id=_concept_id(normalized_name),
                    name=concept.name.strip(),
                    state="touched",
                )
            )
        return updates


def _iter_function_calls(response) -> Iterator[dict[str, str]]:
    """Yield normalized function call metadata from Responses API output."""

    for item in getattr(response, "output", []) or []:
        item_type = getattr(item, "type", None)
        if item_type != "function_call":
            continue
        yield {
            "call_id": getattr(item, "call_id", ""),
            "name": getattr(item, "name", ""),
            "arguments": getattr(item, "arguments", "{}"),
        }


def empty_artifact_event(answer_id: str) -> ArtifactEvent:
    """Return contract-valid empty artifact event when no artifact exists."""

    return ArtifactEvent(
        event="artifact",
        answer_id=answer_id,
        artifact_id="",
        kind="explainer",
        title="",
        url=None,
    )


def _concept_id(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return f"concept_{slug or 'topic'}"


__all__ = ["LLMClient", "FakeLLMClient", "SEARCH_INDEX_TOOL"]
