import type { ArtifactEvent, BenchmarkSummary, CitationChip, ConceptUpdate, IndexEvent, SourceResponse } from "../../types";

export type RouteKey = "workspace" | "chat" | "notebook" | "quiz" | "source" | "developer";
export type ContextTab = "sources" | "notebook" | "quiz";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  artifacts: ArtifactEvent[];
  citations: CitationChip[];
  concepts: ConceptUpdate[];
  steps: string[];
  answerId?: string;
  requestText?: string;
  error?: string;
  pending?: boolean;
}

export interface ArtifactPreview {
  artifactId: string;
  title: string;
  kind: "image" | "text" | "json";
  content: string;
}

export interface QuizReviewItem {
  question: string;
  selectedIndex: number;
  selectedLabel: string;
  correctIndex: number;
  isCorrect: boolean;
  explanation: string;
  chip?: CitationChip;
  concept?: ConceptUpdate;
}

export interface SourceNavItem {
  label: string;
  anchor?: string;
}

export interface SourceAccordionState {
  [messageId: string]: boolean;
}

export interface NoteOverrides {
  hiddenIds: string[];
  pinnedIds: string[];
  renamedTitles: Record<string, string>;
}

export interface QuizState {
  attemptId?: string;
  question?: string;
  options?: string[];
  sourceLabel?: string;
  sourceAnchor?: string;
  explanation?: string;
  lastConcept?: ConceptUpdate;
  progress: string[];
  reviews: QuizReviewItem[];
  completion?: { score: number; total: number };
}

export interface SourceViewState {
  fileId?: string;
  locator?: string;
  response?: SourceResponse;
  citationIndex?: number;
}

export interface DeveloperChunk {
  label: string;
  chunk: string;
}

export interface ConceptSummaryItem {
  id: string;
  name: string;
  touched: number;
  shaky: number;
}

export type { BenchmarkSummary, CitationChip, ConceptUpdate, IndexEvent };
