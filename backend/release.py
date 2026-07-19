"""Release metadata and deterministic fake LLM helpers."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from backend.agent.planner import ExecutionPlan, PlanStep
from backend.config import FIELDNOTES_VERSION, OPENAI_MODEL
from backend.indexer.bm25 import RetrievalChunk, RetrievalProvider, tokenize
from backend.models import ConceptUpdate, QuizQuestionSchema, RouteIntentSchema


class AnalysisScriptSchema(BaseModel):
    """Structured output for local analysis code generation."""

    model_config = ConfigDict(extra="forbid")

    target_file_path: str
    title: str
    needs_chart: bool
    script: str


@dataclass(frozen=True)
class ReleaseMetadata:
    version: str
    openai_model: str


class FakeLLMClient:
    """Deterministic LLM stub for tests, release checks, and offline smoke runs."""

    def __init__(self, model: str = OPENAI_MODEL) -> None:
        self.model = model
        self._last_workspace_snapshot: dict[str, object] = {}

    def classify_intent(self, question: str) -> RouteIntentSchema:
        lowered = question.lower()
        if any(token in lowered for token in {"why", "chart", "anomaly", "trial"}):
            return RouteIntentSchema(intent="analyze", targets=[], connect=True)
        return RouteIntentSchema(intent="retrieve", targets=[], connect=False)

    def resolve_retrieval(
        self,
        question: str,
        retrieval_provider: RetrievalProvider,
    ) -> list[RetrievalChunk]:
        results = retrieval_provider.search(question, limit=5)
        self._last_workspace_snapshot = self._load_workspace_snapshot(retrieval_provider)
        self._last_workspace_snapshot["last_question"] = question
        return results

    def build_plan(self, question: str, intent_result: RouteIntentSchema) -> ExecutionPlan:
        steps = [PlanStep(step_type="retrieve", label="retrieve", query=question, limit=5)]
        if intent_result.intent == "analyze":
            steps.extend(
                [
                    PlanStep(step_type="analyze", label="analyze"),
                    PlanStep(step_type="execute_python", label="execute_python"),
                ]
            )
        steps.extend(
            [
                PlanStep(step_type="summarize", label="summarize"),
                PlanStep(step_type="answer", label="answer"),
            ]
        )
        return ExecutionPlan(
            intent=intent_result.intent,
            rationale="deterministic release fixture",
            steps=steps,
        )

    def execute_plan(self, **kwargs):
        from backend.agent.executor import Executor

        retrieval_provider = kwargs.get("retrieval_provider")
        if retrieval_provider is not None:
            self._last_workspace_snapshot = self._load_workspace_snapshot(retrieval_provider)
            self._last_workspace_snapshot["last_question"] = str(kwargs.get("question", ""))
        return Executor().execute(llm_client=self, **kwargs)

    def stream_grounded_answer(
        self,
        question: str,
        intent: str,
        retrieval_results: list[RetrievalChunk],
        execution_context: str | None = None,
    ):
        answer = self._build_deterministic_answer(
            question=question,
            intent=intent,
            retrieval_results=retrieval_results,
            execution_context=execution_context,
        )
        yield answer
        if execution_context and intent == "analyze":
            yield "Local execution completed."

    def generate_analysis_script(
        self,
        *,
        question: str,
        retrieval_results: list[RetrievalChunk],
        dataset_profiles_json: str,
    ) -> AnalysisScriptSchema:
        profiles = json.loads(dataset_profiles_json)
        file_path = profiles[0]["file_path"]
        return AnalysisScriptSchema(
            target_file_path=file_path,
            title="Release check analysis",
            needs_chart=True,
            script=(
                "import base64, json, os\n"
                "from pathlib import Path\n"
                "import pandas as pd\n"
                f"frame = pd.read_csv({file_path!r})\n"
                "summary = {'rows': int(len(frame)), 'columns': list(frame.columns)}\n"
                "png_bytes = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO7Z0XQAAAAASUVORK5CYII=')\n"
                "Path(os.environ['FIELDNOTES_CHART_PATH']).write_bytes(png_bytes)\n"
                "Path(os.environ['FIELDNOTES_RESULT_PATH']).write_text(json.dumps({'summary': 'release check complete', 'metrics': summary}), encoding='utf-8')\n"
            ),
        )

    def generate_quiz_question(
        self,
        retrieval_results: list[RetrievalChunk],
        concept_ids: list[str] | None = None,
    ) -> QuizQuestionSchema:
        first = retrieval_results[0]
        correct = first.relative_path
        distractors = [
            correct,
            "notes.md",
            "pendulum_summary.pdf",
            "pendulum.csv",
            "lecture_deck.pptx",
        ]
        options: list[str] = []
        for item in distractors:
            if item not in options:
                options.append(item)
        return QuizQuestionSchema(
            question="Which source contains grounded beta-release material?",
            options=options[:4],
            correct_index=0,
            concept=(concept_ids or ["grounding"])[0],
            source_anchor=f"{first.file_id}#{first.anchor}",
        )

    def extract_concepts(
        self,
        question: str,
        retrieval_results: list[RetrievalChunk],
    ) -> list[ConceptUpdate]:
        return [
            ConceptUpdate(
                concept_id="concept_grounding",
                name="grounding",
                state="touched",
            )
        ]

    def _build_deterministic_answer(
        self,
        *,
        question: str,
        intent: str,
        retrieval_results: list[RetrievalChunk],
        execution_context: str | None,
    ) -> str:
        lowered = question.lower().strip()

        metadata_answer = self._answer_metadata_question(lowered)
        if metadata_answer is not None:
            return metadata_answer

        if self._is_summary_question(lowered):
            summary = self._summarize_retrieval(retrieval_results)
            if summary is None:
                return "I couldn't find enough supporting information in the indexed workspace."
            return summary

        if not self._has_supporting_retrieval(retrieval_results):
            return "I couldn't find enough supporting information in the indexed workspace."

        stitched = self._stitch_retrieval(retrieval_results)
        if stitched is None:
            return "I couldn't find enough supporting information in the indexed workspace."

        if intent == "analyze" and execution_context:
            return f"{stitched}\n\nExecution context:\n{execution_context}"
        return stitched

    def _answer_metadata_question(self, lowered: str) -> str | None:
        file_records = list(self._last_workspace_snapshot.get("files", []))
        file_count = len(file_records)
        if "how many files" in lowered and ("indexed" in lowered or "are there" in lowered):
            return f"{file_count} files are indexed."
        if "list every document" in lowered or "list all documents" in lowered:
            if not file_records:
                return "I couldn't find enough supporting information in the indexed workspace."
            return "Indexed documents:\n" + "\n".join(f"- {record['path']}" for record in file_records)
        if "what pdfs" in lowered or "which pdfs" in lowered:
            pdfs = [record["path"] for record in file_records if record["kind"] == "pdf"]
            if not pdfs:
                return "I couldn't find enough supporting information in the indexed workspace."
            return "Indexed PDFs:\n" + "\n".join(f"- {path}" for path in pdfs)
        if "title of this book" in lowered or "what is the title" in lowered:
            title = self._detect_title(file_records)
            if title is None:
                return "I couldn't find enough supporting information in the indexed workspace."
            return f"Detected title: {title}"
        return None

    def _load_workspace_snapshot(self, retrieval_provider: RetrievalProvider) -> dict[str, object]:
        connection = getattr(retrieval_provider, "connection", None)
        if connection is None:
            return {}
        rows = connection.execute(
            """
            SELECT id, path, kind, display_name
            FROM files
            ORDER BY path
            """
        ).fetchall()
        return {
            "files": [
                {
                    "id": str(row["id"]),
                    "path": str(row["path"]),
                    "kind": str(row["kind"]),
                    "display_name": str(row["display_name"]),
                }
                for row in rows
            ]
        }

    def _detect_title(self, file_records: list[dict[str, str]]) -> str | None:
        candidates = [record["display_name"] for record in file_records if record["kind"] in {"pdf", "docx", "md", "txt"}]
        if not candidates:
            return None
        best = sorted(candidates, key=lambda item: (0 if item.lower().endswith(".pdf") else 1, len(item)))[0]
        stem = Path(best).stem.replace("_", " ").replace("-", " ").strip()
        return stem or Path(best).name

    def _is_summary_question(self, lowered: str) -> bool:
        summary_markers = [
            "summarize",
            "summary",
            "what is this book about",
            "what is this chapter about",
            "explain this chapter",
        ]
        return any(marker in lowered for marker in summary_markers)

    def _has_supporting_retrieval(self, retrieval_results: list[RetrievalChunk]) -> bool:
        if not retrieval_results:
            return False
        query_tokens = {
            token
            for token in tokenize(self._last_workspace_snapshot.get("last_question", ""))
            if token not in {"what", "which", "this", "that", "about", "does", "workspace", "say"}
        }
        if not query_tokens:
            return any(result.score > 0 for result in retrieval_results)
        for result in retrieval_results:
            chunk_tokens = set(tokenize(result.chunk))
            if query_tokens & chunk_tokens:
                return True
        return False

    def _summarize_retrieval(self, retrieval_results: list[RetrievalChunk]) -> str | None:
        sentences = self._dedupe_sentences(retrieval_results, limit=6)
        if not sentences:
            return None
        return " ".join(sentences)

    def _stitch_retrieval(self, retrieval_results: list[RetrievalChunk]) -> str | None:
        sentences = self._dedupe_sentences(retrieval_results, limit=5)
        if not sentences:
            return None
        return " ".join(sentences)

    def _dedupe_sentences(self, retrieval_results: list[RetrievalChunk], limit: int) -> list[str]:
        seen: set[str] = set()
        sentences: list[str] = []
        for result in retrieval_results:
            for sentence in self._split_sentences(result.chunk):
                normalized = re.sub(r"\s+", " ", sentence).strip()
                key = normalized.lower()
                if len(normalized) < 20 or key in seen:
                    continue
                seen.add(key)
                sentences.append(normalized)
                if len(sentences) >= limit:
                    return sentences
        return sentences

    def _split_sentences(self, text: str) -> list[str]:
        return [
            segment.strip()
            for segment in re.split(r"(?<=[.!?])\s+|\n+", text)
            if segment.strip()
        ]


RELEASE_METADATA = ReleaseMetadata(version=FIELDNOTES_VERSION, openai_model=OPENAI_MODEL)
