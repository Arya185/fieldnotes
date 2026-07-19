export type Intent =
  | "retrieve"
  | "analyze"
  | "visualize"
  | "connect"
  | "quiz";

export type ParseStatus = "parsed" | "failed" | "skipped";
export type StepType =
  | "retrieval"
  | "codegen"
  | "execution"
  | "grounding"
  | "retry";
export type StepStatus = "started" | "ok" | "failed";
export type CitationChipType = "document" | "code";
export type ConceptState = "touched" | "shaky";
export type ArtifactKind = "chart" | "script" | "explainer";
export type StarterSeed = "anomaly" | "concept" | "practice";
export type ColumnDType = "int" | "float" | "string" | "bool" | "datetime";
export type ArtifactCardKind = "chart" | "explainer" | "quiz_result" | "script";

export interface StarterCard {
  text: string;
  file_path: string;
  seed: StarterSeed;
}

export interface WorkspaceBrief {
  course_title: string;
  summary: string;
  starter_cards:
    | [StarterCard, StarterCard, StarterCard]
    | [StarterCard, StarterCard, StarterCard, StarterCard];
}

export interface FileStartedEvent {
  event: "file_started";
  file_id: string;
  display_name: string;
}

export interface FileParsedEvent {
  event: "file_parsed";
  file_id: string;
  display_name: string;
  parse_status: ParseStatus;
  parse_summary: string;
}

export interface IndexCompleteEvent {
  event: "index_complete";
  file_count: number;
  chunk_count: number;
}

export interface BriefReadyEvent {
  event: "brief_ready";
  brief: WorkspaceBrief;
}

export type IndexEvent =
  | FileStartedEvent
  | FileParsedEvent
  | IndexCompleteEvent
  | BriefReadyEvent;

export interface CitationChip {
  chip_type: CitationChipType;
  label: string;
  anchor?: string;
  artifact_id?: string;
}

export interface ConceptUpdate {
  concept_id: string;
  name: string;
  state: ConceptState;
}

export interface IntentEvent {
  event: "intent";
  answer_id: string;
  intent: Intent;
  targets: string[];
  connect: boolean;
}

export interface StepEvent {
  event: "step";
  answer_id: string;
  step: StepType;
  label: string;
  status: StepStatus;
  duration_ms?: number;
  file_id?: string;
}

export interface TokenEvent {
  event: "token";
  answer_id: string;
  text: string;
}

export interface ArtifactEvent {
  event: "artifact";
  answer_id: string;
  artifact_id: string;
  kind: ArtifactKind;
  title: string;
  url?: string;
}

export interface CitationsEvent {
  event: "citations";
  answer_id: string;
  chips: CitationChip[];
}

export interface ConceptsEvent {
  event: "concepts";
  answer_id: string;
  updates: ConceptUpdate[];
}

export interface ErrorEvent {
  event: "error";
  answer_id: string;
  message: string;
  recoverable: boolean;
}

export interface DoneEvent {
  event: "done";
  answer_id: string;
}

export type AskEvent =
  | IntentEvent
  | StepEvent
  | TokenEvent
  | ArtifactEvent
  | CitationsEvent
  | ConceptsEvent
  | ErrorEvent
  | DoneEvent;

export interface QuestionEvent {
  event: "question";
  attempt_id: string;
  index: number;
  total: number;
  question: string;
  options: string[];
  source_label: string;
  source_anchor: string;
}

export interface GradedEvent {
  event: "graded";
  attempt_id: string;
  is_correct: boolean;
  correct_index: number;
  explanation: string;
  chip: CitationChip;
  concept_update: ConceptUpdate;
}

export interface QuizDoneEvent {
  event: "quiz_done";
  score: number;
  total: number;
  artifact_id: string;
  refreshed_starters: StarterCard[];
}

export type QuizEvent = QuestionEvent | GradedEvent | QuizDoneEvent;

export interface RouteIntentSchema {
  intent: Intent;
  targets: string[];
  connect: boolean;
}

export interface QuizQuestionSchema {
  question: string;
  options: [string, string, string, string];
  correct_index: number;
  concept: string;
  source_anchor: string;
}

export interface OutlierFlag {
  group: string;
  metric: string;
  z_score: number;
}

export interface ColumnProfile {
  name: string;
  dtype: ColumnDType;
  null_count: number;
  min?: number;
  max?: number;
  mean?: number;
  std?: number;
  distinct_count?: number;
  top_values?: string[];
  outlier_flags?: OutlierFlag[];
}

export interface DatasetProfile {
  file_path: string;
  row_count: number;
  columns: ColumnProfile[];
  notes: string[];
}

export interface IndexRequest {
  folder_path: string;
}

export interface IndexAcceptedResponse {
  status: "accepted";
  workspace_id: string;
  run_id: string;
  events: string;
}

export interface AskRequest {
  workspace_id: string;
  question: string;
}

export interface QuizRequest {
  workspace_id: string;
  concept_ids: string[] | null;
}

export interface QuizAnswerRequest {
  workspace_id: string;
  attempt_id: string;
  chosen_index: number;
}

export interface ArtifactCard {
  id: string;
  kind: ArtifactCardKind;
  title: string;
  created_at: string;
  url?: string;
}

export interface NotebookResponse {
  artifacts: ArtifactCard[];
}

export interface SourceResponse {
  text: string;
  label: string;
  file_path: string;
}

export interface RetrievalInspectionRecord {
  file_id: string;
  relative_path: string;
  anchor: string;
  chunk: string;
  score: number;
  diagnostics?: Record<string, unknown>;
  reason?: string;
}

export interface BenchmarkSummary {
  latency_summary: Record<
    string,
    {
      count: number;
      min: number;
      max: number;
      avg: number;
    }
  >;
  retrieval_metrics: {
    before: Record<string, number>;
    after: Record<string, number>;
  };
  execution_metrics: Record<string, number>;
  regression_comparison: Record<string, unknown>;
}

export interface HealthResponse {
  status: string;
  version: string;
  mode: "live" | "fake";
  startup: string;
}
