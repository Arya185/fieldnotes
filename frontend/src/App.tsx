import { useDeferredValue, useEffect, useMemo, useRef, useState } from "react";

import { LockBadge } from "./components/LockBadge";
import { Composer } from "./components/Composer";
import { EmptyState } from "./components/EmptyState";
import { WorkspaceOverview } from "./components/WorkspaceOverview";
import { MarkdownBlock } from "./lib/markdown";
import {
  fetchArtifact,
  getHealth,
  getNotebook,
  getSource,
  openAskStream,
  openIndexEvents,
  openQuizAnswerStream,
  openQuizStartStream,
  postIndex,
} from "./lib/api";
import {
  loadDeveloperMode,
  loadIndexHistory,
  loadRecentWorkspaces,
  saveDeveloperMode,
  saveIndexHistory,
  saveRecentWorkspaces,
  type IndexHistoryEntry,
  type StoredWorkspaceRecord,
} from "./lib/storage";
import type {
  ArtifactCard,
  ArtifactEvent,
  AskEvent,
  BenchmarkSummary,
  CitationChip,
  ConceptUpdate,
  IndexEvent,
  NotebookResponse,
  QuizEvent,
  SourceResponse,
} from "./types";
import "./styles.css";

type RouteKey = "workspace" | "chat" | "notebook" | "quiz" | "source" | "developer";

interface ChatMessage {
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

interface ArtifactPreview {
  artifactId: string;
  title: string;
  kind: "image" | "text" | "json";
  content: string;
}

interface QuizReviewItem {
  question: string;
  selectedIndex: number;
  selectedLabel: string;
  correctIndex: number;
  isCorrect: boolean;
  explanation: string;
  chip?: CitationChip;
  concept?: ConceptUpdate;
}

interface SourceNavItem {
  label: string;
  anchor?: string;
}

interface SourceAccordionState {
  [messageId: string]: boolean;
}

interface NoteOverrides {
  hiddenIds: string[];
  pinnedIds: string[];
  renamedTitles: Record<string, string>;
}

const routes: RouteKey[] = ["workspace", "chat", "notebook", "quiz", "source", "developer"];
const PINNED_ARTIFACTS_KEY = "fieldnotes.pinnedArtifacts";
const NOTE_OVERRIDES_KEY = "fieldnotes.noteOverrides";

function getInitialRoute(): RouteKey {
  const hash = window.location.hash.replace("#", "") as RouteKey;
  return routes.includes(hash) ? hash : "workspace";
}

function formatDateTime(value?: string): string {
  if (!value) {
    return "Never";
  }
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

function formatRelative(value?: string): string {
  if (!value) {
    return "not yet";
  }
  const delta = Date.now() - new Date(value).getTime();
  const mins = Math.max(0, Math.round(delta / 60000));
  if (mins < 1) {
    return "just now";
  }
  if (mins < 60) {
    return `${mins}m ago`;
  }
  const hours = Math.round(mins / 60);
  if (hours < 24) {
    return `${hours}h ago`;
  }
  return `${Math.round(hours / 24)}d ago`;
}

function readPinnedArtifacts(): string[] {
  if (typeof window === "undefined") {
    return [];
  }
  const raw = window.localStorage.getItem(PINNED_ARTIFACTS_KEY);
  if (!raw) {
    return [];
  }
  try {
    return JSON.parse(raw) as string[];
  } catch {
    return [];
  }
}

function writePinnedArtifacts(value: string[]): void {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.setItem(PINNED_ARTIFACTS_KEY, JSON.stringify(value));
}

function readNoteOverrides(): NoteOverrides {
  if (typeof window === "undefined") {
    return { hiddenIds: [], pinnedIds: [], renamedTitles: {} };
  }
  const raw = window.localStorage.getItem(NOTE_OVERRIDES_KEY);
  if (!raw) {
    return { hiddenIds: [], pinnedIds: [], renamedTitles: {} };
  }
  try {
    const parsed = JSON.parse(raw) as Partial<NoteOverrides>;
    return {
      hiddenIds: parsed.hiddenIds ?? [],
      pinnedIds: parsed.pinnedIds ?? [],
      renamedTitles: parsed.renamedTitles ?? {},
    };
  } catch {
    return { hiddenIds: [], pinnedIds: [], renamedTitles: {} };
  }
}

function writeNoteOverrides(value: NoteOverrides): void {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.setItem(NOTE_OVERRIDES_KEY, JSON.stringify(value));
}

async function copyText(text: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }
  throw new Error("Clipboard unavailable");
}

export default function App() {
  const [route, setRoute] = useState<RouteKey>(getInitialRoute);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [contextPanelOpen, setContextPanelOpen] = useState(false);
  const [contextTab, setContextTab] = useState<"sources" | "notebook" | "quiz">("sources");
  const [recentWorkspaces, setRecentWorkspaces] = useState<StoredWorkspaceRecord[]>(loadRecentWorkspaces);
  const [indexHistory, setIndexHistory] = useState<IndexHistoryEntry[]>(loadIndexHistory);
  const [developerMode, setDeveloperMode] = useState<boolean>(loadDeveloperMode);
  const [folderPath, setFolderPath] = useState("");
  const [activeWorkspaceId, setActiveWorkspaceId] = useState<string | null>(
    () => loadRecentWorkspaces()[0]?.workspaceId ?? null,
  );
  const [chatInput, setChatInput] = useState("");
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [starterSummary, setStarterSummary] = useState("No workspace indexed yet. Drop workspace path or type absolute folder path.");
  const [indexEvents, setIndexEvents] = useState<IndexEvent[]>([]);
  const [notebook, setNotebook] = useState<NotebookResponse>({ artifacts: [] });
  const [artifactFilter, setArtifactFilter] = useState("all");
  const [artifactSearch, setArtifactSearch] = useState("");
  const [artifactSort, setArtifactSort] = useState<"newest" | "oldest">("newest");
  const [artifactPreview, setArtifactPreview] = useState<ArtifactPreview | null>(null);
  const [pinnedArtifacts, setPinnedArtifacts] = useState<string[]>(readPinnedArtifacts);
  const [noteOverrides, setNoteOverrides] = useState<NoteOverrides>(readNoteOverrides);
  const [quizState, setQuizState] = useState<{
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
  }>({ progress: [], reviews: [] });
  const [incorrectReviewOnly, setIncorrectReviewOnly] = useState(false);
  const [sourceView, setSourceView] = useState<{
    fileId?: string;
    locator?: string;
    response?: SourceResponse;
    citationIndex?: number;
  }>({});
  const [developerSummary, setDeveloperSummary] = useState<BenchmarkSummary | null>(null);
  const [developerChunks, setDeveloperChunks] = useState<Array<{ label: string; chunk: string }>>([]);
  const [busy, setBusy] = useState(false);
  const [statusMessage, setStatusMessage] = useState("Ready.");
  const [streamingAnswerId, setStreamingAnswerId] = useState<string | null>(null);
  const [typingIndicator, setTypingIndicator] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const [runtimeMode, setRuntimeMode] = useState<"live" | "fake" | null>(null);
  const [sourceSearch, setSourceSearch] = useState("");
  const [sourcePanelExpanded, setSourcePanelExpanded] = useState(true);
  const [allSourcesExpanded, setAllSourcesExpanded] = useState(false);
  const chatScrollRef = useRef<HTMLDivElement | null>(null);
  const composerRef = useRef<HTMLTextAreaElement | null>(null);
  const askAbortRef = useRef<AbortController | null>(null);
  const indexAbortRef = useRef<AbortController | null>(null);
  const autoScrollRef = useRef(true);
  const [sourceAccordionState, setSourceAccordionState] = useState<SourceAccordionState>({});

  const activeWorkspace = recentWorkspaces.find((workspace) => workspace.workspaceId === activeWorkspaceId);
  const indexedDocumentCount = useMemo(() => {
    const latest = indexHistory.find((entry) => entry.workspaceId === activeWorkspaceId && entry.fileCount !== undefined);
    return latest?.fileCount ?? 0;
  }, [activeWorkspaceId, indexHistory]);
  const lastIndexEntry = useMemo(
    () => indexHistory.find((entry) => entry.workspaceId === activeWorkspaceId),
    [activeWorkspaceId, indexHistory],
  );

  useEffect(() => {
    window.location.hash = route;
  }, [route]);

  useEffect(() => {
    saveRecentWorkspaces(recentWorkspaces);
  }, [recentWorkspaces]);

  useEffect(() => {
    saveIndexHistory(indexHistory);
  }, [indexHistory]);

  useEffect(() => {
    saveDeveloperMode(developerMode);
  }, [developerMode]);

  useEffect(() => {
    writePinnedArtifacts(pinnedArtifacts);
  }, [pinnedArtifacts]);

  useEffect(() => {
    writeNoteOverrides(noteOverrides);
  }, [noteOverrides]);

  useEffect(() => {
    if (!activeWorkspaceId) {
      setNotebook({ artifacts: [] });
      return;
    }
    void getNotebook(activeWorkspaceId)
      .then(setNotebook)
      .catch((error: Error) => {
        setNotebook({ artifacts: [] });
        setErrorMessage(`Notebook load failed: ${error.message}`);
      });
  }, [activeWorkspaceId]);

  useEffect(() => {
    void getHealth()
      .then((health) => setRuntimeMode(health.mode))
      .catch(() => setRuntimeMode(null));
  }, []);

  useEffect(() => {
    if (route === "chat") {
      composerRef.current?.focus();
    }
    if (route === "notebook") {
      setContextTab("notebook");
      setContextPanelOpen(true);
    }
    if (route === "quiz") {
      setContextTab("quiz");
      setContextPanelOpen(true);
    }
    if (route === "source") {
      setContextTab("sources");
      setContextPanelOpen(true);
    }
  }, [route]);

  useEffect(() => {
    const node = chatScrollRef.current;
    if (!node || route !== "chat" || !autoScrollRef.current) {
      return;
    }
    node.scrollTop = node.scrollHeight;
  }, [chatMessages, route, typingIndicator]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        composerRef.current?.focus();
      }
      if (event.key === "Escape" && askAbortRef.current) {
        event.preventDefault();
        handleCancelResponse();
      }
      if ((event.metaKey || event.ctrlKey) && event.shiftKey && event.key.toLowerCase() === "r") {
        event.preventDefault();
        void handleRetryLast();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [chatMessages]);

  const allCitations = useMemo(
    () =>
      chatMessages.flatMap((message) =>
        message.citations.map((chip) => ({
          messageId: message.id,
          label: chip.label,
          anchor: chip.anchor,
        })),
      ),
    [chatMessages],
  );
  const sourceNavItems = useMemo<SourceNavItem[]>(
    () =>
      allCitations.slice(0, 10).map((citation) => ({
        label: citation.label,
        anchor: citation.anchor,
      })),
    [allCitations],
  );
  const deferredArtifactSearch = useDeferredValue(artifactSearch);

  const filteredArtifacts = useMemo(() => {
    const visibleArtifacts = notebook.artifacts.filter((artifact) => !noteOverrides.hiddenIds.includes(artifact.id));
    const base =
      artifactFilter === "all"
        ? visibleArtifacts
        : visibleArtifacts.filter((artifact) => artifact.kind === artifactFilter);
    const searched = base.filter((artifact) =>
      [(noteOverrides.renamedTitles[artifact.id] ?? artifact.title), artifact.kind]
        .join(" ")
        .toLowerCase()
        .includes(deferredArtifactSearch.toLowerCase()),
    );
    const sorted = [...searched].sort((left, right) => {
      const leftTime = new Date(left.created_at).getTime();
      const rightTime = new Date(right.created_at).getTime();
      return artifactSort === "newest" ? rightTime - leftTime : leftTime - rightTime;
    });
    sorted.sort(
      (left, right) =>
        Number((noteOverrides.pinnedIds.includes(right.id) || pinnedArtifacts.includes(right.id))) -
        Number((noteOverrides.pinnedIds.includes(left.id) || pinnedArtifacts.includes(left.id))),
    );
    return sorted;
  }, [artifactFilter, artifactSort, deferredArtifactSearch, notebook.artifacts, noteOverrides, pinnedArtifacts]);

  const sourceSearchResults = useMemo(() => {
    const text = sourceView.response?.text ?? "";
    const query = sourceSearch.trim().toLowerCase();
    if (!query || !text) {
      return [];
    }
    const haystack = text.toLowerCase();
    const matches: number[] = [];
    let startIndex = 0;
    while (startIndex < haystack.length) {
      const found = haystack.indexOf(query, startIndex);
      if (found === -1) {
        break;
      }
      matches.push(found);
      startIndex = found + query.length;
      if (matches.length >= 20) {
        break;
      }
    }
    return matches;
  }, [sourceSearch, sourceView.response?.text]);

  const conceptSummary = useMemo(() => {
    const map = new Map<string, { name: string; touched: number; shaky: number }>();
    chatMessages.flatMap((message) => message.concepts).forEach((concept) => {
      const current = map.get(concept.concept_id) ?? { name: concept.name, touched: 0, shaky: 0 };
      if (concept.state === "touched") {
        current.touched += 1;
      } else {
        current.shaky += 1;
      }
      map.set(concept.concept_id, current);
    });
    quizState.reviews.forEach((review) => {
      if (!review.concept) {
        return;
      }
      const current = map.get(review.concept.concept_id) ?? { name: review.concept.name, touched: 0, shaky: 0 };
      if (review.concept.state === "touched") {
        current.touched += 1;
      } else {
        current.shaky += 1;
      }
      map.set(review.concept.concept_id, current);
    });
    return [...map.entries()].map(([id, value]) => ({ id, ...value }));
  }, [chatMessages, quizState.reviews]);

  function updateWorkspaceRecord(workspaceId: string, update: Partial<StoredWorkspaceRecord>) {
    setRecentWorkspaces((current) =>
      current.map((item) => (item.workspaceId === workspaceId ? { ...item, ...update } : item)),
    );
  }

  function validateWorkspace(folder: string): string | null {
    const trimmed = folder.trim();
    if (!trimmed) {
      return "Workspace folder required.";
    }
    if (!trimmed.startsWith("/") && !/^[A-Za-z]:[\\/]/.test(trimmed)) {
      return "Workspace path must be absolute.";
    }
    return null;
  }

  async function loadNotebookForWorkspace(workspaceId: string) {
    try {
      const data = await getNotebook(workspaceId);
      setNotebook(data);
    } catch (error) {
      setErrorMessage(`Workspace not found: ${(error as Error).message}`);
      setNotebook({ artifacts: [] });
    }
  }

  function renameArtifact(artifact: ArtifactCard) {
    const nextTitle = window.prompt("Rename note", noteOverrides.renamedTitles[artifact.id] ?? artifact.title);
    if (!nextTitle?.trim()) {
      return;
    }
    setNoteOverrides((current) => ({
      ...current,
      renamedTitles: {
        ...current.renamedTitles,
        [artifact.id]: nextTitle.trim(),
      },
    }));
    setStatusMessage("Note renamed.");
  }

  function deleteArtifact(artifact: ArtifactCard) {
    if (!window.confirm(`Remove "${noteOverrides.renamedTitles[artifact.id] ?? artifact.title}" from notebook view?`)) {
      return;
    }
    setNoteOverrides((current) => ({
      ...current,
      hiddenIds: [...new Set([...current.hiddenIds, artifact.id])],
    }));
    setStatusMessage("Note removed from current workspace view.");
  }

  function clearActiveWorkspace() {
    if (!activeWorkspace || !window.confirm(`Clear workspace "${activeWorkspace.title}" from recent list?`)) {
      return;
    }
    setRecentWorkspaces((current) => current.filter((item) => item.workspaceId !== activeWorkspace.workspaceId));
    setIndexHistory((current) => current.filter((item) => item.workspaceId !== activeWorkspace.workspaceId));
    setActiveWorkspaceId((current) =>
      current === activeWorkspace.workspaceId ? recentWorkspaces.find((item) => item.workspaceId !== current)?.workspaceId ?? null : current,
    );
    setNotebook({ artifacts: [] });
    setChatMessages([]);
    setSourceView({});
    setStatusMessage("Workspace cleared from recent list.");
  }

  async function handleIndex(folder: string, force = false) {
    const validationError = validateWorkspace(folder);
    if (validationError) {
      setErrorMessage(validationError);
      setStatusMessage(validationError);
      return;
    }
    if (
      !force &&
      activeWorkspace &&
      activeWorkspace.folderPath === folder.trim() &&
      !window.confirm("Re-index selected workspace?")
    ) {
      return;
    }
    setBusy(true);
    setErrorMessage(null);
    setStatusMessage("Indexing workspace...");
    indexAbortRef.current?.abort();
    const accepted = await postIndex({ folder_path: folder.trim() });
    const record: StoredWorkspaceRecord = {
      workspaceId: accepted.workspace_id,
      folderPath: folder.trim(),
      title: folder.trim().split(/[\\/]/).filter(Boolean).slice(-1)[0] ?? folder.trim(),
      lastIndexedAt: new Date().toISOString(),
      lastRunId: accepted.run_id,
      status: "indexing",
    };
    setRecentWorkspaces((current) => {
      const next = [record, ...current.filter((item) => item.workspaceId !== record.workspaceId)];
      return next.slice(0, 8);
    });
    setActiveWorkspaceId(record.workspaceId);
    setIndexHistory((current) => [
      {
        runId: accepted.run_id,
        workspaceId: accepted.workspace_id,
        startedAt: new Date().toISOString(),
        status: "accepted",
      },
      ...current,
    ]);
    setIndexEvents([]);
    const controller = new AbortController();
    indexAbortRef.current = controller;
    void openIndexEvents(
      accepted.events,
      (event) => {
        setIndexEvents((current) => [...current, event]);
        if (event.event === "brief_ready") {
          setStarterSummary(event.brief.summary);
          updateWorkspaceRecord(accepted.workspace_id, {
            status: "ready",
            lastIndexedAt: new Date().toISOString(),
            lastRunId: accepted.run_id,
          });
          setIndexHistory((current) =>
            current.map((entry) =>
              entry.runId === accepted.run_id
                ? { ...entry, status: "completed", finishedAt: new Date().toISOString() }
                : entry,
            ),
          );
          setStatusMessage("Workspace indexed.");
          setBusy(false);
          void loadNotebookForWorkspace(accepted.workspace_id);
        }
        if (event.event === "index_complete") {
          setIndexHistory((current) =>
            current.map((entry) =>
              entry.runId === accepted.run_id
                ? {
                    ...entry,
                    fileCount: event.file_count,
                    chunkCount: event.chunk_count,
                    status: "running",
                  }
                : entry,
            ),
          );
        }
      },
      controller.signal,
    ).catch((error: Error) => {
      if (error.name === "AbortError") {
        return;
      }
      updateWorkspaceRecord(accepted.workspace_id, { status: "error" });
      setIndexHistory((current) =>
        current.map((entry) =>
          entry.runId === accepted.run_id
            ? { ...entry, status: "failed", finishedAt: new Date().toISOString() }
            : entry,
        ),
      );
      setErrorMessage(`Indexing failed: ${error.message}`);
      setStatusMessage(error.message);
      setBusy(false);
    });
  }

  async function requestAnswer(userText: string, mode: "new" | "retry" | "regenerate") {
    if (!activeWorkspaceId || !userText.trim()) {
      return;
    }
    setErrorMessage(null);
    askAbortRef.current?.abort();
    const userMessage: ChatMessage | null =
      mode === "new"
        ? {
            id: `user-${Date.now()}`,
            role: "user",
            text: userText,
            artifacts: [],
            citations: [],
            concepts: [],
            steps: [],
            requestText: userText,
          }
        : null;
    const assistantMessage: ChatMessage = {
      id: `assistant-${Date.now()}`,
      role: "assistant",
      text: "",
      artifacts: [],
      citations: [],
      concepts: [],
      steps: [],
      pending: true,
      requestText: userText,
    };
    setChatInput("");
    setBusy(true);
    setTypingIndicator(true);
    setStatusMessage("Streaming answer...");
    setDeveloperChunks([]);
    setStreamingAnswerId(assistantMessage.id);
    setChatMessages((current) =>
      mode === "new"
        ? [...current, userMessage!, assistantMessage]
        : [...current, assistantMessage],
    );

    const controller = new AbortController();
    askAbortRef.current = controller;

    await openAskStream(
      { workspace_id: activeWorkspaceId, question: userText },
      async (event: AskEvent) => {
        setChatMessages((current) =>
          current.map((message) => {
            if (message.id !== assistantMessage.id) {
              return message;
            }
            if (event.event === "intent") {
              return { ...message, answerId: event.answer_id };
            }
            if (event.event === "token") {
              return { ...message, answerId: event.answer_id, text: `${message.text}${event.text}`, pending: false };
            }
            if (event.event === "artifact") {
              return { ...message, answerId: event.answer_id, artifacts: [...message.artifacts, event], pending: false };
            }
            if (event.event === "citations") {
              return { ...message, answerId: event.answer_id, citations: event.chips, pending: false };
            }
            if (event.event === "concepts") {
              return { ...message, answerId: event.answer_id, concepts: event.updates, pending: false };
            }
            if (event.event === "step") {
              return { ...message, answerId: event.answer_id, steps: [...message.steps, `${event.step}: ${event.label}`], pending: true };
            }
            if (event.event === "error") {
              return {
                ...message,
                answerId: event.answer_id,
                error: event.message,
                text: `${message.text}\n\nError: ${event.message}`.trim(),
                pending: false,
              };
            }
            if (event.event === "done") {
              return { ...message, answerId: event.answer_id, pending: false };
            }
            return message;
          }),
        );

        if (event.event === "citations") {
          const chunks = await Promise.all(
            event.chips
              .filter((chip) => chip.anchor && chip.anchor.includes("#"))
              .map(async (chip) => {
                const [fileId, locator] = chip.anchor!.split("#");
                const response = await getSource(activeWorkspaceId, fileId, locator);
                return { label: chip.label, chunk: response.text };
              }),
          );
          setDeveloperChunks(chunks);
        }

        if (event.event === "done") {
          setBusy(false);
          setTypingIndicator(false);
          setStreamingAnswerId(null);
          setStatusMessage("Answer complete.");
          void loadNotebookForWorkspace(activeWorkspaceId);
        }
      },
      controller.signal,
    ).catch((error: Error) => {
      if (error.name === "AbortError") {
        setStatusMessage("Response canceled.");
        setTypingIndicator(false);
        setBusy(false);
        setStreamingAnswerId(null);
        return;
      }
      setBusy(false);
      setTypingIndicator(false);
      setStreamingAnswerId(null);
      setErrorMessage(`Ask failed: ${error.message}`);
      setStatusMessage(error.message);
      setChatMessages((current) =>
        current.map((message) =>
          message.id === assistantMessage.id
            ? { ...message, error: error.message, pending: false, text: message.text || `Error: ${error.message}` }
            : message,
        ),
      );
    });
  }

  async function handleAsk() {
    await requestAnswer(chatInput, "new");
  }

  function handleCancelResponse() {
    askAbortRef.current?.abort();
    setTypingIndicator(false);
    setBusy(false);
    setChatMessages((current) =>
      current.map((message) =>
        message.id === streamingAnswerId
          ? { ...message, pending: false, error: "Canceled by user." }
          : message,
      ),
    );
  }

  async function handleRetryLast() {
    const lastPrompt = [...chatMessages].reverse().find((message) => message.role === "user")?.text;
    if (!lastPrompt) {
      return;
    }
    await requestAnswer(lastPrompt, "retry");
  }

  async function handleRegenerate() {
    const lastPrompt = [...chatMessages].reverse().find((message) => message.role === "user")?.text;
    if (!lastPrompt) {
      return;
    }
    await requestAnswer(lastPrompt, "regenerate");
  }

  async function handleOpenArtifact(card: ArtifactCard) {
    if (!activeWorkspaceId) {
      return;
    }
    try {
      const response = await fetchArtifact(activeWorkspaceId, card.id);
      const contentType = response.headers.get("content-type") ?? "";
      if (contentType.includes("image")) {
        const blob = await response.blob();
        setArtifactPreview({
          artifactId: card.id,
          title: card.title,
          kind: "image",
          content: URL.createObjectURL(blob),
        });
        setContextTab("notebook");
        setContextPanelOpen(true);
        setRoute("notebook");
        return;
      }
      const text = await response.text();
      if (!text.trim()) {
        throw new Error("Artifact empty.");
      }
      setArtifactPreview({
        artifactId: card.id,
        title: card.title,
        kind: text.trim().startsWith("{") ? "json" : "text",
        content: text,
      });
      setContextTab("notebook");
      setContextPanelOpen(true);
      setRoute("notebook");
    } catch (error) {
      setErrorMessage(`Artifact open failed: ${(error as Error).message}`);
    }
  }

  async function handleStartQuiz(restart = false) {
    if (!activeWorkspaceId) {
      return;
    }
    setBusy(true);
    setErrorMessage(null);
    setStatusMessage(restart ? "Restarting quiz..." : "Generating quiz...");
    await openQuizStartStream(
      { workspace_id: activeWorkspaceId, concept_ids: null },
      (event: QuizEvent) => {
        if (event.event === "question") {
          setQuizState((current) => ({
            ...current,
            attemptId: event.attempt_id,
            question: event.question,
            options: event.options,
            sourceLabel: event.source_label,
            sourceAnchor: event.source_anchor,
            explanation: undefined,
            lastConcept: undefined,
            completion: undefined,
            progress: restart ? [`Question: ${event.question}`] : [...current.progress, `Question: ${event.question}`],
          }));
          setBusy(false);
          setStatusMessage("Quiz ready.");
        }
      },
    ).catch((error: Error) => {
      setBusy(false);
      setErrorMessage(`Quiz start failed: ${error.message}`);
      setStatusMessage(error.message);
    });
  }

  async function handleAnswerQuiz(choice: number) {
    if (!activeWorkspaceId || !quizState.attemptId || !quizState.question) {
      return;
    }
    setBusy(true);
    setStatusMessage("Checking answer...");
    await openQuizAnswerStream(
      {
        workspace_id: activeWorkspaceId,
        attempt_id: quizState.attemptId,
        chosen_index: choice,
      },
      (event: QuizEvent) => {
        if (event.event === "graded") {
          setQuizState((current) => ({
            ...current,
            explanation: event.explanation,
            lastConcept: event.concept_update,
            reviews: [
              ...current.reviews,
              {
                question: current.question ?? "",
                selectedIndex: choice,
                selectedLabel: current.options?.[choice] ?? "",
                correctIndex: event.correct_index,
                isCorrect: event.is_correct,
                explanation: event.explanation,
                chip: event.chip,
                concept: event.concept_update,
              },
            ],
            progress: [...current.progress, `Graded: ${event.is_correct ? "correct" : "incorrect"}`],
          }));
        }
        if (event.event === "quiz_done") {
          setQuizState((current) => ({
            ...current,
            completion: { score: event.score, total: event.total },
            progress: [...current.progress, `Done: ${event.score}/${event.total}`],
          }));
          setBusy(false);
          setStatusMessage("Quiz complete.");
          void loadNotebookForWorkspace(activeWorkspaceId);
        }
      },
    ).catch((error: Error) => {
      setBusy(false);
      setErrorMessage(`Quiz answer failed: ${error.message}`);
      setStatusMessage(error.message);
    });
  }

  async function handleJumpToSource(anchor: string | undefined) {
    if (!activeWorkspaceId || !anchor || !anchor.includes("#")) {
      return;
    }
    try {
      const [fileId, locator] = anchor.split("#");
      const response = await getSource(activeWorkspaceId, fileId, locator);
      const citationIndex = allCitations.findIndex((item) => item.anchor === anchor);
      setSourceView({ fileId, locator, response, citationIndex });
      setContextTab("sources");
      setContextPanelOpen(true);
      setRoute("source");
    } catch (error) {
      setErrorMessage(`Source open failed: ${(error as Error).message}`);
    }
  }

  function handleSourceNav(direction: -1 | 1) {
    if (sourceView.citationIndex === undefined) {
      return;
    }
    const next = allCitations[sourceView.citationIndex + direction];
    if (next?.anchor) {
      void handleJumpToSource(next.anchor);
    }
  }

  function handleBenchmarkImport(file: File | null) {
    if (!file) {
      return;
    }
    const readText = typeof file.text === "function" ? file.text() : new Response(file).text();
    void readText
      .then((text) => setDeveloperSummary(JSON.parse(text) as BenchmarkSummary))
      .catch((error: Error) => {
        setErrorMessage(`Benchmark import failed: ${error.message}`);
        setStatusMessage(error.message);
      });
  }

  function handleDropWorkspace(event: React.DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragActive(false);
    const text = event.dataTransfer.getData("text/plain").trim();
    const filePath =
      text ||
      Array.from(event.dataTransfer.files)
        .map((file) => (file as File & { path?: string; webkitRelativePath?: string }).path ?? file.webkitRelativePath)
        .find(Boolean) ||
      "";
    if (filePath) {
      setFolderPath(filePath);
      setStatusMessage("Workspace path loaded.");
    }
  }

  async function exportConversation() {
    const content = chatMessages
      .map((message) => {
        const title = message.role === "assistant" ? "## Fieldnotes" : "## You";
        const citations =
          message.citations.length > 0
            ? `\n\nCitations:\n${message.citations.map((chip) => `- ${chip.label}${chip.anchor ? ` (${chip.anchor})` : ""}`).join("\n")}`
            : "";
        return `${title}\n\n${message.text}${citations}`;
      })
      .join("\n\n");
    await copyText(content);
    setStatusMessage("Conversation markdown copied.");
  }

  async function exportArtifact(card: ArtifactCard) {
    if (!activeWorkspaceId) {
      return;
    }
    try {
      const response = await fetchArtifact(activeWorkspaceId, card.id);
      const text = await response.text();
      await copyText(text);
      setStatusMessage("Artifact markdown copied.");
    } catch (error) {
      setErrorMessage(`Artifact export failed: ${(error as Error).message}`);
    }
  }

  async function copyCitation(chip: CitationChip) {
    await copyText(`${chip.label}${chip.anchor ? ` (${chip.anchor})` : ""}`);
    setStatusMessage("Citation copied.");
  }

  async function copyAnswer(message: ChatMessage) {
    await copyText(message.text);
    setStatusMessage("Answer copied.");
  }

  const reviewItems = incorrectReviewOnly
    ? quizState.reviews.filter((item) => !item.isCorrect)
    : quizState.reviews;
  const activeWorkspaceHistory = indexHistory.filter((entry) => entry.workspaceId === activeWorkspaceId);
  const indexedPages = activeWorkspaceHistory.reduce((max, entry) => Math.max(max, entry.chunkCount ?? 0), 0);
  const fileTypeSummary = useMemo(() => {
    const extensions = recentWorkspaces
      .filter((workspace) => workspace.workspaceId === activeWorkspaceId)
      .flatMap((workspace) => workspace.folderPath.split(".").slice(1))
      .filter(Boolean);
    return extensions.length > 0 ? extensions.join(", ") : "mixed";
  }, [activeWorkspaceId, recentWorkspaces]);
  const noBackend = runtimeMode === null && errorMessage?.toLowerCase().includes("failed");

  const chatRouteActive = route === "chat";
  const showFullNotebook = route === "notebook";
  const showFullQuiz = route === "quiz";
  const showFullSource = route === "source";

  function renderEmptyState(title: string, body: string, actionLabel?: string, action?: () => void) {
    return <EmptyState title={title} body={body} actionLabel={actionLabel} onAction={action} />;
  }

  return (
    <div
      className={`app-shell ${developerMode ? "dev-on" : ""} ${dragActive ? "drag-on" : ""} ${
        sidebarCollapsed ? "sidebar-collapsed" : ""
      } ${contextPanelOpen ? "context-open" : "context-closed"}`}
    >
      <div className="sr-only" aria-live="polite">
        {typingIndicator ? "Assistant typing." : statusMessage}
      </div>

      <aside className="sidebar panel">
        <section className="section sidebar-top">
          <div className="brand brand-tight">
            <div>
              <h1>Fieldnotes</h1>
              {!sidebarCollapsed && <p>Grounded local study workspace.</p>}
            </div>
            <div className="toolbar compact">
              <button
                className="icon-button"
                onClick={() => setSidebarCollapsed((current) => !current)}
                aria-label={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
              >
                {sidebarCollapsed ? "›" : "‹"}
              </button>
            </div>
          </div>
          {!sidebarCollapsed && (
            <div className="sidebar-badges">
              <LockBadge />
              {runtimeMode === "fake" && <span className="pill">Fake Mode (Deterministic)</span>}
            </div>
          )}
        </section>

        <section
          className={`section stack drop-zone ${dragActive ? "drag-active" : ""}`}
          onDragOver={(event) => {
            event.preventDefault();
            setDragActive(true);
          }}
          onDragLeave={() => setDragActive(false)}
          onDrop={handleDropWorkspace}
        >
          <div className="split-row">
            <div>
              <div className="eyebrow">Workspace</div>
              {!sidebarCollapsed && <strong>Study folder</strong>}
            </div>
            {!sidebarCollapsed && <span className="pill">{activeWorkspace?.status ?? "none"}</span>}
          </div>
          <input
            aria-label="Workspace folder"
            className="input"
            placeholder={sidebarCollapsed ? "/path..." : "/path/to/workspace"}
            value={folderPath}
            onChange={(event) => setFolderPath(event.target.value)}
          />
          {!sidebarCollapsed && (
            <p className="muted">
              Drag a folder path here where the browser supports it. Absolute path only.
            </p>
          )}
          <div className="toolbar compact">
            <button className="button" onClick={() => void handleIndex(folderPath)} disabled={busy}>
              {sidebarCollapsed ? "Index" : "Index Workspace"}
            </button>
            <button
              className="button secondary"
              onClick={() => activeWorkspace && void handleIndex(activeWorkspace.folderPath)}
              disabled={!activeWorkspace || busy}
            >
              {sidebarCollapsed ? "Retry" : "Re-index"}
            </button>
            {!sidebarCollapsed && (
              <button className="button ghost" onClick={clearActiveWorkspace} disabled={!activeWorkspace}>
                Clear Workspace
              </button>
            )}
          </div>
          {!sidebarCollapsed && <p className="muted">{starterSummary}</p>}
          {!sidebarCollapsed && !activeWorkspace && (
            <div className="hint-card">Start by choosing a workspace, indexing it, then asking grounded questions.</div>
          )}
          {!sidebarCollapsed && runtimeMode === null && (
            <div className="hint-card">Fake mode startup or backend startup still pending. If this persists, start backend and refresh.</div>
          )}
        </section>

        <section className="section">
          <div className="split-row">
            <div>
              <div className="eyebrow">Library</div>
              {!sidebarCollapsed && <strong>Recent workspaces</strong>}
            </div>
            <button
              className="button ghost"
              onClick={() => setDeveloperMode((current) => !current)}
              aria-label={developerMode ? "Hide developer mode" : "Show developer mode"}
            >
              {developerMode ? "Hide Dev" : "Show Dev"}
            </button>
          </div>
          <div className="stack">
            {recentWorkspaces.map((workspace) => (
              <button
                key={workspace.workspaceId}
                className={`workspace-card ${workspace.workspaceId === activeWorkspaceId ? "active" : ""}`}
                onClick={() => {
                  setActiveWorkspaceId(workspace.workspaceId);
                  setRoute("chat");
                  void loadNotebookForWorkspace(workspace.workspaceId);
                }}
              >
                <header>
                  <div className="workspace-title-row">
                    <span className="workspace-icon" aria-hidden="true">📄</span>
                    <strong>{workspace.title}</strong>
                  </div>
                  {!sidebarCollapsed && (
                    <span className={`pill ${workspace.status === "ready" ? "success" : workspace.status === "error" ? "danger" : ""}`}>
                      {workspace.status}
                    </span>
                  )}
                </header>
                {!sidebarCollapsed && <p className="muted">{workspace.folderPath}</p>}
                {!sidebarCollapsed && (
                  <p className="muted">Indexed {formatRelative(workspace.lastIndexedAt)} · {formatDateTime(workspace.lastIndexedAt)}</p>
                )}
              </button>
            ))}
          </div>
        </section>

        {!sidebarCollapsed && (
          <section className="section sidebar-bottom">
            <div className="eyebrow">History</div>
            <strong>Recent indexing runs</strong>
            <div className="history-list">
              {indexHistory.slice(0, 6).map((entry) => (
                <article className="history-card compact-card" key={`${entry.runId}-${entry.startedAt}`}>
                  <header>
                    <strong>{entry.workspaceId}</strong>
                    <span className={`pill ${entry.status === "failed" ? "danger" : ""}`}>{entry.status}</span>
                  </header>
                  <p className="muted">{entry.fileCount ?? 0} files · {entry.chunkCount ?? 0} chunks</p>
                  <p className="muted">{formatDateTime(entry.startedAt)}</p>
                </article>
              ))}
            </div>
          </section>
        )}
      </aside>

      <main className="main-panel panel">
        <header className="main-header modern-header">
          <div className="main-header-copy">
            <div className="tabs" role="tablist" aria-label="Primary navigation">
              {routes
                .filter((item) => developerMode || item !== "developer")
                .map((item) => (
                  <button
                    key={item}
                    className="tab"
                    aria-selected={route === item}
                    onClick={() => setRoute(item)}
                  >
                    {item}
                  </button>
                ))}
            </div>
            <div className="hero-inline">
              <div>
                <h2>
                  {chatRouteActive && "Ask your workspace"}
                  {showFullNotebook && "Notebook"}
                  {showFullQuiz && "Study mode"}
                  {showFullSource && "Source viewer"}
                  {route === "workspace" && "Workspace overview"}
                  {route === "developer" && "Developer diagnostics"}
                </h2>
                <p className="muted">{statusMessage}</p>
              </div>
              {chatRouteActive && (
                <div className="toolbar compact">
                  <button className="context-toggle" onClick={() => { setContextTab("sources"); setContextPanelOpen((current) => !current); }}>
                    {contextPanelOpen ? "Hide Context" : "Show Context"}
                  </button>
                </div>
              )}
            </div>
            {errorMessage && <p className="error-banner" role="alert">{errorMessage}</p>}
          </div>
          <div className="header-badges">
            <div className="pill">{activeWorkspace?.title ?? "No workspace selected"}</div>
            <div className="pill">{indexedDocumentCount} docs</div>
          </div>
        </header>

        <div
          className={`main-scroll ${chatRouteActive ? "chat-scroll" : ""}`}
          ref={route === "chat" ? chatScrollRef : undefined}
          onScroll={(event) => {
            if (route !== "chat") {
              return;
            }
            const node = event.currentTarget;
            const nearBottom = node.scrollHeight - node.scrollTop - node.clientHeight < 64;
            autoScrollRef.current = nearBottom;
          }}
        >
          {route === "workspace" && (
            <WorkspaceOverview
              activeWorkspace={activeWorkspace}
              starterSummary={starterSummary}
              indexedDocumentCount={indexedDocumentCount}
              indexedPages={indexedPages}
              lastIndexEntry={lastIndexEntry}
              fileTypeSummary={fileTypeSummary}
              indexEvents={indexEvents}
              runtimeMode={runtimeMode}
              busy={busy}
              noBackend={Boolean(noBackend)}
              formatDateTime={formatDateTime}
              formatRelative={formatRelative}
            />
          )}

          {route === "chat" && (
            <section className="chat-layout">
              <div className="chat-toolbar">
                <button className="button secondary" onClick={() => void handleRetryLast()} disabled={busy || chatMessages.length === 0}>
                  Retry Last
                </button>
                <button className="button secondary" onClick={() => void handleRegenerate()} disabled={busy || chatMessages.length === 0}>
                  Regenerate
                </button>
                <button className="button ghost" onClick={handleCancelResponse} disabled={!busy}>
                  Cancel
                </button>
                <button className="button ghost" onClick={() => void exportConversation()} disabled={chatMessages.length === 0}>
                  Export Markdown
                </button>
              </div>

              {busy && (
                <div className="stream-banner" aria-live="polite">
                  <span className="stream-dot" aria-hidden="true" />
                  Streaming answer. Auto-scroll stays locked unless you scroll away.
                </div>
              )}

              {chatMessages.length === 0 && (
                <div className="empty-chat-state">
                  <div className="eyebrow">Ready to study</div>
                  <h3>Ask questions grounded in your indexed files.</h3>
                  <p>
                    Reading comes first here: answers stay tied to sources, notebook artifacts stay close at hand, and quiz mode is one click away.
                  </p>
                  <div className="empty-chat-prompts">
                    <button className="suggestion-chip" onClick={() => setChatInput("Summarize the main ideas in this workspace.")}>
                      Summarize this workspace
                    </button>
                    <button className="suggestion-chip" onClick={() => setChatInput("List the most important documents to read first.")}>
                      What should I read first?
                    </button>
                    <button className="suggestion-chip" onClick={() => setChatInput("Create a study guide from the indexed sources.")}>
                      Create a study guide
                    </button>
                  </div>
                </div>
              )}

              {chatMessages.map((message) => (
                <article className={`message-card polished-message ${message.role}`} key={message.id}>
                  <div className="message-meta">
                    <strong>{message.role === "assistant" ? "Fieldnotes" : "You"}</strong>
                    {message.steps.length > 0 && <span>{message.steps[message.steps.length - 1]}</span>}
                  </div>
                  <div className="message-body-wrap">
                    <MarkdownBlock text={message.text || (message.pending ? "…" : "")} />
                  </div>
                  {message.pending && <div className="typing-indicator" aria-label="Typing indicator">Fieldnotes typing…</div>}
                  {message.role === "assistant" && (
                    <div className="toolbar compact">
                      <button className="button secondary" onClick={() => void copyAnswer(message)} disabled={!message.text}>
                        Copy Answer
                      </button>
                      {message.requestText && (
                        <button className="button ghost" onClick={() => void requestAnswer(message.requestText!, "regenerate")} disabled={busy}>
                          Regenerate
                        </button>
                      )}
                    </div>
                  )}
                  {message.artifacts.length > 0 && (
                    <div className="stack">
                      {message.artifacts.map((artifact) => (
                        <div className="artifact-preview" key={`${message.id}-${artifact.artifact_id}-${artifact.title}`}>
                          <div className="split-row">
                            <strong>{artifact.title || artifact.kind}</strong>
                            <button
                              className="button secondary"
                              onClick={() =>
                                void handleOpenArtifact({
                                  id: artifact.artifact_id,
                                  kind: artifact.kind === "script" ? "script" : artifact.kind === "chart" ? "chart" : "explainer",
                                  title: artifact.title,
                                  created_at: new Date().toISOString(),
                                  url: artifact.url,
                                })
                              }
                            >
                              Open
                            </button>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                  {message.citations.length > 0 && (
                    <details
                      className="sources-disclosure"
                      open={sourceAccordionState[message.id] ?? allSourcesExpanded}
                      onToggle={(event) =>
                        setSourceAccordionState((current) => ({
                          ...current,
                          [message.id]: (event.currentTarget as HTMLDetailsElement).open,
                        }))
                      }
                    >
                      <summary>Sources ({message.citations.length})</summary>
                      <div className="sources-list">
                        {message.citations.map((chip, index) => (
                          <div className="source-row" key={`${message.id}-citation-${index}`}>
                            <button
                              className={`source-link ${sourceView.locator && chip.anchor?.endsWith(sourceView.locator) ? "source-link-active" : ""}`}
                              onClick={() => void handleJumpToSource(chip.anchor)}
                            >
                              {chip.label}
                            </button>
                            <button className="mini-action" aria-label={`Copy citation ${chip.label}`} onClick={() => void copyCitation(chip)}>
                              Copy
                            </button>
                          </div>
                        ))}
                      </div>
                    </details>
                  )}
                  {message.concepts.length > 0 && (
                    <div className="chip-row">
                      {message.concepts.map((concept) => (
                        <span className="pill" key={concept.concept_id}>
                          {concept.name}: {concept.state}
                        </span>
                      ))}
                    </div>
                  )}
                </article>
              ))}
              {chatMessages.length > 0 && (
                <div className="toolbar compact chat-footer-tools">
                  <button
                    className="button ghost"
                    onClick={() => setAllSourcesExpanded((current) => !current)}
                  >
                    {allSourcesExpanded ? "Collapse All Sources" : "Expand All Sources"}
                  </button>
                  <span className="muted">Shortcuts: Cmd/Ctrl+Enter send, Cmd/Ctrl+K focus, Escape stop.</span>
                </div>
              )}
            </section>
          )}

          {route === "notebook" && (
            <section className="workspace-overview stack">
              <div className="section-heading">
                <div>
                  <div className="eyebrow">Notebook</div>
                  <h3>Saved artifacts</h3>
                </div>
              </div>
              <div className="toolbar">
                {["all", "explainer", "script", "chart", "quiz_result"].map((kind) => (
                  <button
                    key={kind}
                    className="tab"
                    aria-selected={artifactFilter === kind}
                    onClick={() => setArtifactFilter(kind)}
                  >
                    {kind}
                  </button>
                ))}
              </div>
              <div className="toolbar">
                <input
                  aria-label="Search artifacts"
                  className="input"
                  placeholder="Search artifacts"
                  value={artifactSearch}
                  onChange={(event) => setArtifactSearch(event.target.value)}
                />
                <select
                  aria-label="Sort artifacts"
                  className="select"
                  value={artifactSort}
                  onChange={(event) => setArtifactSort(event.target.value as "newest" | "oldest")}
                >
                  <option value="newest">Newest</option>
                  <option value="oldest">Oldest</option>
                </select>
              </div>
              {notebook.artifacts.length === 0 &&
                renderEmptyState(
                  "No notebook entries",
                  "Artifacts appear after answers, quizzes, or analysis runs. Ask workspace question to start collecting reusable notes.",
                  "Go To Chat",
                  () => setRoute("chat"),
                )}
              <div className="artifact-list">
                {filteredArtifacts.map((artifact) => (
                  <article className="artifact-card notebook-card" key={artifact.id}>
                    <header>
                      <div>
                        <strong>{noteOverrides.renamedTitles[artifact.id] ?? artifact.title}</strong>
                        <p className="muted">{artifact.kind} · {formatDateTime(artifact.created_at)}</p>
                      </div>
                      <div className="toolbar">
                        <button className="button secondary" onClick={() => void handleOpenArtifact(artifact)}>
                          Reopen
                        </button>
                        <button
                          className="button ghost"
                          onClick={() =>
                            setPinnedArtifacts((current) =>
                              current.includes(artifact.id)
                                ? current.filter((item) => item !== artifact.id)
                                : [artifact.id, ...current],
                            )
                          }
                        >
                          {pinnedArtifacts.includes(artifact.id) ? "Unpin" : "Pin"}
                        </button>
                        <button className="button ghost" onClick={() => renameArtifact(artifact)}>
                          Rename
                        </button>
                        <button className="button ghost" onClick={() => void exportArtifact(artifact)}>
                          Export
                        </button>
                        <button
                          className="button ghost"
                          onClick={() => {
                            setChatInput(`Use artifact ${artifact.title} in answer.`);
                            setRoute("chat");
                          }}
                        >
                          Ask With
                        </button>
                        <button
                          className="button ghost"
                          onClick={() => deleteArtifact(artifact)}
                        >
                          Delete
                        </button>
                      </div>
                    </header>
                  </article>
                ))}
              </div>
              {notebook.artifacts.length > 0 && filteredArtifacts.length === 0 && (
                <div className="hint-card">No search results. Change note query or switch artifact filter.</div>
              )}
              {artifactPreview && (
                <article className="artifact-card">
                  <header>
                    <strong>{artifactPreview.title}</strong>
                    <span className="pill">{artifactPreview.kind}</span>
                  </header>
                  {artifactPreview.kind === "image" ? (
                    <img alt={artifactPreview.title} src={artifactPreview.content} />
                  ) : artifactPreview.kind === "json" ? (
                    <pre>{artifactPreview.content}</pre>
                  ) : (
                    <MarkdownBlock text={artifactPreview.content} />
                  )}
                </article>
              )}
            </section>
          )}

          {route === "quiz" && (
            <section className="workspace-overview stack">
              <div className="section-heading">
                <div>
                  <div className="eyebrow">Quiz</div>
                  <h3>Study mode</h3>
                </div>
              </div>
              <div className="toolbar">
                <button className="button" onClick={() => void handleStartQuiz(false)} disabled={!activeWorkspaceId || busy}>
                  Start Quiz
                </button>
                <button className="button secondary" onClick={() => void handleStartQuiz(true)} disabled={!activeWorkspaceId || busy}>
                  Restart Quiz
                </button>
                <button
                  className="button ghost"
                  onClick={() => setIncorrectReviewOnly((current) => !current)}
                  disabled={quizState.reviews.length === 0}
                >
                  {incorrectReviewOnly ? "Show All Review" : "Incorrect Review"}
                </button>
              </div>
              {!quizState.question &&
                !quizState.completion &&
                renderEmptyState(
                  "No quiz generated",
                  "Start quiz after indexing workspace. Fieldnotes builds questions from current source set.",
                  "Generate Quiz",
                  () => void handleStartQuiz(false),
                )}
              {quizState.question && (
                <article className="quiz-card study-card">
                  <div className="quiz-kicker">Question</div>
                  <div className="quiz-progress-row">
                    <span className="pill">Progress {Math.min(quizState.reviews.length + 1, (quizState.completion?.total ?? 1))}/{quizState.completion?.total ?? 1}</span>
                    {quizState.reviews.length > 0 && <span className="pill">Score {quizState.reviews.filter((item) => item.isCorrect).length}</span>}
                  </div>
                  <strong className="quiz-question">{quizState.question}</strong>
                  <div className="quiz-options">
                    {quizState.options?.map((option, index) => (
                      <button
                        className="quiz-option"
                        key={`${option}-${index}`}
                        onClick={() => void handleAnswerQuiz(index)}
                        disabled={busy}
                      >
                        {option}
                      </button>
                    ))}
                  </div>
                  {quizState.explanation && (
                    <details className="quiz-explanation" open>
                      <summary>Explanation</summary>
                      <p>{quizState.explanation}</p>
                    </details>
                  )}
                  {quizState.lastConcept && (
                    <span className="pill">
                      {quizState.lastConcept.name}: {quizState.lastConcept.state}
                    </span>
                  )}
                </article>
              )}
              {quizState.completion && (
                <div className="finish-card">
                  <div className="eyebrow">Finish Screen</div>
                  <h3>Completion summary: {quizState.completion.score}/{quizState.completion.total}</h3>
                  <p>Review explanations, retry incorrect answers, or start fresh run when ready.</p>
                  <div className="toolbar compact">
                    <button className="button secondary" onClick={() => setIncorrectReviewOnly(true)} disabled={quizState.reviews.every((item) => item.isCorrect)}>
                      Retry Incorrect
                    </button>
                    <button className="button ghost" onClick={() => void handleStartQuiz(true)}>
                      Start Fresh
                    </button>
                  </div>
                </div>
              )}
              <div className="grid-two">
                <div className="history-list">
                  {reviewItems.map((item, index) => (
                    <div className="history-card" key={`${item.question}-${index}`}>
                      <strong>{item.question}</strong>
                      <p className="muted">You chose: {item.selectedLabel}</p>
                      <p className="muted">Correct index: {item.correctIndex}</p>
                      <p>{item.explanation}</p>
                      {item.chip && (
                        <button className="chip" onClick={() => void handleJumpToSource(item.chip?.anchor)}>
                          {item.chip.label}
                        </button>
                      )}
                    </div>
                  ))}
                </div>
                <div className="history-list">
                  <div className="history-card">
                    <strong>Concept Progress</strong>
                    {conceptSummary.length === 0 && <p className="muted">No concept updates yet.</p>}
                    {conceptSummary.map((concept) => (
                      <div className="progress-meter" key={concept.id}>
                        <span>{concept.name}</span>
                        <div className="meter-bar">
                          <div className="meter-fill" style={{ width: `${Math.min(100, concept.touched * 25 + concept.shaky * 10)}%` }} />
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
              <div className="history-list">
                {quizState.progress.map((entry, index) => (
                  <div className="history-card" key={`${entry}-${index}`}>
                    {entry}
                  </div>
                ))}
              </div>
            </section>
          )}

          {route === "source" && (
            <section className="workspace-overview stack">
              <div className="section-heading">
                <div>
                  <div className="eyebrow">Source</div>
                  <h3>Grounding view</h3>
                </div>
              </div>
              <div className="toolbar">
                <button
                  className="button secondary"
                  onClick={() => quizState.sourceAnchor && void handleJumpToSource(quizState.sourceAnchor)}
                  disabled={!quizState.sourceAnchor}
                >
                  Open Quiz Citation
                </button>
                <button className="button secondary" onClick={() => handleSourceNav(-1)} disabled={sourceView.citationIndex === undefined || sourceView.citationIndex < 1}>
                  Previous Citation
                </button>
                <button className="button secondary" onClick={() => handleSourceNav(1)} disabled={sourceView.citationIndex === undefined || sourceView.citationIndex >= allCitations.length - 1}>
                  Next Citation
                </button>
                <button
                  className="button ghost"
                  onClick={() =>
                    sourceView.response &&
                    void copyText(`${sourceView.response.file_path} -> ${sourceView.response.label} -> ${sourceView.locator ?? ""}`)
                  }
                  disabled={!sourceView.response}
                >
                  Copy Source Ref
                </button>
                <button className="button ghost" onClick={() => setSourcePanelExpanded((current) => !current)} disabled={!sourceView.response}>
                  {sourcePanelExpanded ? "Collapse Source" : "Expand Source"}
                </button>
              </div>
              {sourceView.response ? (
                <article className="source-card polished-source-card">
                  <header>
                    <div>
                      <strong>{sourceView.response.label}</strong>
                      <p className="muted">{sourceView.response.file_path}</p>
                      <p className="breadcrumb">
                        {sourceView.response.file_path} → {sourceView.response.label} → {sourceView.locator}
                      </p>
                    </div>
                    <span className="pill">{sourceView.locator}</span>
                  </header>
                  <div className="toolbar compact source-tools">
                    <input
                      aria-label="Search within source"
                      className="input"
                      placeholder="Search within source"
                      value={sourceSearch}
                      onChange={(event) => {
                        const nextValue = event.target.value;
                        setSourceSearch(nextValue);
                      }}
                    />
                    <span className="pill">
                      Page {sourceView.locator?.split("/")[0] ?? "current"}
                    </span>
                    <span className="pill">
                      {sourceSearchResults.length > 0 ? `${sourceSearchResults.length} matches` : "No search results"}
                    </span>
                  </div>
                  {sourcePanelExpanded && (
                    <div className="source-text">
                      <span className="highlight">{sourceView.response.text}</span>
                    </div>
                  )}
                </article>
              ) : (
                renderEmptyState(
                  "No source selected",
                  "Open citation from chat or quiz. Fieldnotes will jump straight to cited passage and keep locator visible.",
                )
              )}
            </section>
          )}

          {route === "developer" && developerMode && (
            <section className="developer-grid">
              <article className="dev-card">
                <header>
                  <strong>Retrieval Transparency</strong>
                  <input
                    aria-label="Load benchmark summary"
                    className="input"
                    type="file"
                    accept="application/json"
                    onChange={(event) => handleBenchmarkImport(event.target.files?.[0] ?? null)}
                  />
                </header>
                <div className="stack">
                  <div className="history-card">
                    <strong>Live Trace Timeline</strong>
                    {chatMessages.flatMap((message) => message.steps).map((step, index) => (
                      <div className="timeline-row" key={`${step}-${index}`}>
                        <span className="pill">{index + 1}</span>
                        <span>{step}</span>
                      </div>
                    ))}
                  </div>
                  <div className="history-card">
                    <strong>Planner Execution Graph</strong>
                    {chatMessages.flatMap((message) => message.steps).map((step, index) => (
                      <div key={`${step}-graph-${index}`}>{index === 0 ? "start" : "↓"} {step}</div>
                    ))}
                  </div>
                  <div className="history-card">
                    <strong>Final Grounded Chunks</strong>
                    {developerChunks.length > 0 ? (
                      developerChunks.map((chunk, index) => (
                        <div key={`${chunk.label}-${index}`}>
                          <strong>{chunk.label}</strong>
                          <p>{chunk.chunk}</p>
                        </div>
                      ))
                    ) : (
                      <p className="muted">Current backend transport exposes only final cited chunks.</p>
                    )}
                  </div>
                </div>
              </article>

              <article className="dev-card">
                <strong>Observability</strong>
                {developerSummary ? (
                  <div className="stack">
                    <div className="table-wrap">
                      <table>
                        <thead>
                          <tr>
                            <th>Metric</th>
                            <th>Avg</th>
                            <th>Max</th>
                          </tr>
                        </thead>
                        <tbody>
                          {Object.entries(developerSummary.latency_summary).map(([key, value]) => (
                            <tr key={key}>
                              <td>{key}</td>
                              <td>{value.avg.toFixed(2)}</td>
                              <td>{value.max.toFixed(2)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    <div className="history-card">
                      <strong>Latency Charts</strong>
                      {Object.entries(developerSummary.latency_summary).map(([key, value]) => (
                        <div className="progress-meter" key={`lat-${key}`}>
                          <span>{key}</span>
                          <div className="meter-bar">
                            <div className="meter-fill accent" style={{ width: `${Math.min(100, value.avg)}%` }} />
                          </div>
                        </div>
                      ))}
                    </div>
                    <div className="history-card">
                      <strong>Retrieval Score Breakdown</strong>
                      <pre>{JSON.stringify(developerSummary.retrieval_metrics, null, 2)}</pre>
                    </div>
                    <div className="history-card">
                      <strong>Reranking Decisions</strong>
                      <pre>{JSON.stringify(developerSummary.regression_comparison ?? {}, null, 2)}</pre>
                    </div>
                    <div className="history-card">
                      <strong>Execution Metrics</strong>
                      <pre>{JSON.stringify(developerSummary.execution_metrics, null, 2)}</pre>
                    </div>
                  </div>
                ) : (
                  <p className="muted">
                    Import benchmark JSON from `scripts/benchmarks_latest.json` to inspect traces, latencies, benchmark summaries.
                  </p>
                )}
              </article>
            </section>
          )}
        </div>

        {route === "chat" && (
          <Composer
            value={chatInput}
            inputRef={composerRef}
            activeWorkspaceId={activeWorkspaceId}
            busy={busy}
            onChange={setChatInput}
            onSubmit={() => void handleAsk()}
            onCancel={handleCancelResponse}
          />
        )}
      </main>

      <aside className="rightbar panel">
        <section className="section context-header">
          <div className="split-row">
            <div>
              <div className="eyebrow">Context Panel</div>
              <strong>Sources, notebook, study</strong>
            </div>
            <button
              className="icon-button"
              onClick={() => setContextPanelOpen((current) => !current)}
              aria-label={contextPanelOpen ? "Collapse context panel" : "Expand context panel"}
            >
              {contextPanelOpen ? "›" : "‹"}
            </button>
          </div>
        </section>

        <section className="section context-tabs">
          <button className="tab" aria-selected={contextTab === "sources"} onClick={() => { setContextTab("sources"); setContextPanelOpen(true); }}>
            Sources
          </button>
          <button className="tab" aria-selected={contextTab === "notebook"} onClick={() => { setContextTab("notebook"); setContextPanelOpen(true); }}>
            Notebook
          </button>
          <button className="tab" aria-selected={contextTab === "quiz"} onClick={() => { setContextTab("quiz"); setContextPanelOpen(true); }}>
            Quiz
          </button>
        </section>

        {contextPanelOpen && (
          <>
            <section className="section">
              <strong>Workspace Status</strong>
              <div className="grid-two">
                <div className="workspace-card">
                  <div className="muted">Workspace</div>
                  <strong>{activeWorkspace?.title ?? "None"}</strong>
                </div>
                <div className="workspace-card">
                  <div className="muted">Artifacts</div>
                  <strong>{notebook.artifacts.length}</strong>
                </div>
              </div>
            </section>

            {contextTab === "sources" && (
              <section className="section context-body">
                <strong>Source trail</strong>
                {sourceView.response ? (
                  <article className="source-card compact-source-card">
                    <header>
                      <div>
                        <strong>{sourceView.response.label}</strong>
                        <p className="muted">{sourceView.response.file_path}</p>
                      </div>
                      <span className="pill">{sourceView.locator}</span>
                    </header>
                    <p className="muted">Open the full source view in the center panel for highlighted passage text.</p>
                  </article>
                ) : (
                  <div className="hint-card">Open source from citation chip. Context panel keeps quick trail while center view shows full passage.</div>
                )}
                <div className="stack">
                  {sourceNavItems.map((item, index) => (
                    <button
                      className={`source-link source-nav-link ${sourceView.citationIndex === index ? "source-link-active" : ""}`}
                      key={`${item.label}-${index}`}
                      onClick={() => void handleJumpToSource(item.anchor)}
                    >
                      {item.label}
                    </button>
                  ))}
                </div>
              </section>
            )}

            {contextTab === "notebook" && (
              <section className="section context-body">
                <strong>Notebook preview</strong>
                {filteredArtifacts.length === 0 ? (
                  <div className="hint-card">No notebook entries yet. Ask question or finish quiz to collect study artifacts.</div>
                ) : (
                <div className="artifact-list">
                  {filteredArtifacts.slice(0, 4).map((artifact) => (
                    <button className="artifact-card notebook-card" key={artifact.id} onClick={() => void handleOpenArtifact(artifact)}>
                      <header>
                        <strong>{noteOverrides.renamedTitles[artifact.id] ?? artifact.title}</strong>
                        <span className="pill">{(noteOverrides.pinnedIds.includes(artifact.id) || pinnedArtifacts.includes(artifact.id)) ? "pinned" : artifact.kind}</span>
                      </header>
                    </button>
                  ))}
                </div>
                )}
              </section>
            )}

            {contextTab === "quiz" && (
              <section className="section context-body">
                <strong>Study progress</strong>
                {quizState.question ? (
                  <div className="history-card">
                    <p className="muted">Current question</p>
                    <strong>Quiz in progress</strong>
                    <p className="muted">Score {quizState.reviews.filter((item) => item.isCorrect).length}/{Math.max(quizState.reviews.length, 1)}</p>
                    {quizState.explanation && <p>{quizState.explanation}</p>}
                  </div>
                ) : (
                  <div className="hint-card">Start a quiz to track progress here.</div>
                )}
                <div className="history-list">
                  {reviewItems.slice(-4).map((item, index) => (
                    <div className="history-card compact-card" key={`${item.question}-${index}`}>
                      <strong>{item.question}</strong>
                      <p className="muted">{item.isCorrect ? "Correct" : "Needs review"}</p>
                    </div>
                  ))}
                </div>
              </section>
            )}
          </>
        )}
      </aside>
    </div>
  );
}
