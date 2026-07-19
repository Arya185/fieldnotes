"""Fieldnotes contract models from docs/schemas.md §2–§5."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    """Base model for schema-derived contract types."""

    model_config = ConfigDict(extra="forbid")


Intent = Literal["retrieve", "analyze", "visualize", "connect", "quiz"]
ParseStatus = Literal["parsed", "failed", "skipped"]
StepType = Literal["retrieval", "codegen", "execution", "grounding", "retry"]
StepStatus = Literal["started", "ok", "failed"]
CitationChipType = Literal["document", "code"]
ConceptState = Literal["touched", "shaky"]
ArtifactKind = Literal["chart", "script", "explainer"]
StarterSeed = Literal["anomaly", "concept", "practice"]
ColumnDType = Literal["int", "float", "string", "bool", "datetime"]
ArtifactCardKind = Literal["chart", "explainer", "quiz_result", "script"]


class StarterCard(StrictModel):
    text: str
    file_path: str
    seed: StarterSeed


class WorkspaceBrief(StrictModel):
    course_title: str
    summary: str
    starter_cards: list[StarterCard] = Field(min_length=3, max_length=4)


class FileStartedEvent(StrictModel):
    event: Literal["file_started"]
    file_id: str
    display_name: str


class FileParsedEvent(StrictModel):
    event: Literal["file_parsed"]
    file_id: str
    display_name: str
    parse_status: ParseStatus
    parse_summary: str


class IndexCompleteEvent(StrictModel):
    event: Literal["index_complete"]
    file_count: int
    chunk_count: int


class BriefReadyEvent(StrictModel):
    event: Literal["brief_ready"]
    brief: WorkspaceBrief


IndexEvent = Annotated[
    FileStartedEvent | FileParsedEvent | IndexCompleteEvent | BriefReadyEvent,
    Field(discriminator="event"),
]


class CitationChip(StrictModel):
    chip_type: CitationChipType
    label: str
    anchor: str | None = None
    artifact_id: str | None = None


class ConceptUpdate(StrictModel):
    concept_id: str
    name: str
    state: ConceptState


class IntentEvent(StrictModel):
    event: Literal["intent"]
    answer_id: str
    intent: Intent
    targets: list[str]
    connect: bool


class StepEvent(StrictModel):
    event: Literal["step"]
    answer_id: str
    step: StepType
    label: str
    status: StepStatus
    duration_ms: int | None = None
    file_id: str | None = None


class TokenEvent(StrictModel):
    event: Literal["token"]
    answer_id: str
    text: str


class ArtifactEvent(StrictModel):
    event: Literal["artifact"]
    answer_id: str
    artifact_id: str
    kind: ArtifactKind
    title: str
    url: str | None = None


class CitationsEvent(StrictModel):
    event: Literal["citations"]
    answer_id: str
    chips: list[CitationChip]


class ConceptsEvent(StrictModel):
    event: Literal["concepts"]
    answer_id: str
    updates: list[ConceptUpdate]


class ErrorEvent(StrictModel):
    event: Literal["error"]
    answer_id: str
    message: str
    recoverable: bool


class DoneEvent(StrictModel):
    event: Literal["done"]
    answer_id: str


AskEvent = Annotated[
    IntentEvent
    | StepEvent
    | TokenEvent
    | ArtifactEvent
    | CitationsEvent
    | ConceptsEvent
    | ErrorEvent
    | DoneEvent,
    Field(discriminator="event"),
]


class QuestionEvent(StrictModel):
    event: Literal["question"]
    attempt_id: str
    index: int
    total: int
    question: str
    options: list[str] = Field(min_length=4, max_length=4)
    source_label: str
    source_anchor: str


class GradedEvent(StrictModel):
    event: Literal["graded"]
    attempt_id: str
    is_correct: bool
    correct_index: int
    explanation: str
    chip: CitationChip
    concept_update: ConceptUpdate


class QuizDoneEvent(StrictModel):
    event: Literal["quiz_done"]
    score: int
    total: int
    artifact_id: str
    refreshed_starters: list[StarterCard]


QuizEvent = Annotated[
    QuestionEvent | GradedEvent | QuizDoneEvent,
    Field(discriminator="event"),
]


class RouteIntentSchema(StrictModel):
    intent: Intent
    targets: list[str]
    connect: bool


class QuizQuestionSchema(StrictModel):
    question: str
    options: list[str] = Field(min_length=4, max_length=4)
    correct_index: int
    concept: str
    source_anchor: str


class OutlierFlag(StrictModel):
    group: str
    metric: str
    z_score: float


class ColumnProfile(StrictModel):
    name: str
    dtype: ColumnDType
    null_count: int
    min: float | None = None
    max: float | None = None
    mean: float | None = None
    std: float | None = None
    distinct_count: int | None = None
    top_values: list[str] | None = None
    outlier_flags: list[OutlierFlag] | None = None


class DatasetProfile(StrictModel):
    file_path: str
    row_count: int
    columns: list[ColumnProfile]
    notes: list[str]


class IndexRequest(StrictModel):
    folder_path: str


class AskRequest(StrictModel):
    workspace_id: str
    question: str


class IndexAcceptedResponse(StrictModel):
    status: Literal["accepted"]
    workspace_id: str
    run_id: str
    events: str


class QuizRequest(StrictModel):
    workspace_id: str
    concept_ids: list[str] | None


class QuizAnswerRequest(StrictModel):
    workspace_id: str
    attempt_id: str
    chosen_index: int


class ArtifactCard(StrictModel):
    id: str
    kind: ArtifactCardKind
    title: str
    created_at: str
    url: str | None = None


class NotebookResponse(StrictModel):
    artifacts: list[ArtifactCard]


class SourceResponse(StrictModel):
    text: str
    label: str
    file_path: str
