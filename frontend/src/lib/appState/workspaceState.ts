import type { Dispatch, DragEvent, SetStateAction } from "react";
import { useDeferredValue, useEffect, useMemo, useState } from "react";

import { fetchArtifact, getHealth, getNotebook, getSource, postIndex } from "../api";
import {
  loadDeveloperMode,
  loadIndexHistory,
  loadRecentWorkspaces,
  saveDeveloperMode,
  saveIndexHistory,
  saveRecentWorkspaces,
  type IndexHistoryEntry,
  type StoredWorkspaceRecord,
} from "../storage";
import { useIndexStream } from "../useIndexStream";
import type { ArtifactCard, BenchmarkSummary, IndexEvent, NotebookResponse } from "../../types";
import type { ArtifactPreview, ContextTab, NoteOverrides, RouteKey, SourceViewState } from "./types";

const PINNED_ARTIFACTS_KEY = "fieldnotes.pinnedArtifacts";
const NOTE_OVERRIDES_KEY = "fieldnotes.noteOverrides";
const EMPTY_NOTE_OVERRIDES: NoteOverrides = { hiddenIds: [], pinnedIds: [], renamedTitles: {} };

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

function readNoteOverrides(workspaceId: string | null): NoteOverrides {
  if (typeof window === "undefined") {
    return EMPTY_NOTE_OVERRIDES;
  }
  const raw = window.localStorage.getItem(NOTE_OVERRIDES_KEY);
  if (!raw) {
    return EMPTY_NOTE_OVERRIDES;
  }
  try {
    const parsed = JSON.parse(raw) as Partial<NoteOverrides> | Record<string, Partial<NoteOverrides>>;
    const scoped: Partial<NoteOverrides> =
      workspaceId &&
      !Array.isArray(parsed) &&
      !("hiddenIds" in parsed) &&
      !("pinnedIds" in parsed) &&
      !("renamedTitles" in parsed)
        ? (parsed as Record<string, Partial<NoteOverrides>>)[workspaceId]
        : (parsed as Partial<NoteOverrides>);
    return {
      hiddenIds: scoped?.hiddenIds ?? [],
      pinnedIds: scoped?.pinnedIds ?? [],
      renamedTitles: scoped?.renamedTitles ?? {},
    };
  } catch {
    return EMPTY_NOTE_OVERRIDES;
  }
}

function writeNoteOverrides(workspaceId: string | null, value: NoteOverrides): void {
  if (typeof window === "undefined") {
    return;
  }
  const raw = window.localStorage.getItem(NOTE_OVERRIDES_KEY);
  let current: Record<string, NoteOverrides> = {};
  if (raw) {
    try {
      const parsed = JSON.parse(raw) as Partial<NoteOverrides> | Record<string, NoteOverrides>;
      if (!Array.isArray(parsed) && "hiddenIds" in parsed) {
        current = workspaceId ? { [workspaceId]: parsed as NoteOverrides } : {};
      } else {
        current = (parsed as Record<string, NoteOverrides>) ?? {};
      }
    } catch {
      current = {};
    }
  }
  if (!workspaceId) {
    return;
  }
  current[workspaceId] = value;
  window.localStorage.setItem(NOTE_OVERRIDES_KEY, JSON.stringify(current));
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

interface UseWorkspaceStateArgs {
  setBusy: Dispatch<SetStateAction<boolean>>;
  setErrorMessage: Dispatch<SetStateAction<string | null>>;
  setStatusMessage: Dispatch<SetStateAction<string>>;
  setContextTab: Dispatch<SetStateAction<ContextTab>>;
  setContextPanelOpen: Dispatch<SetStateAction<boolean>>;
  setRoute: Dispatch<SetStateAction<RouteKey>>;
}

export function useWorkspaceState({
  setBusy,
  setErrorMessage,
  setStatusMessage,
  setContextTab,
  setContextPanelOpen,
  setRoute,
}: UseWorkspaceStateArgs) {
  const [recentWorkspaces, setRecentWorkspaces] = useState<StoredWorkspaceRecord[]>(loadRecentWorkspaces);
  const [indexHistory, setIndexHistory] = useState<IndexHistoryEntry[]>(loadIndexHistory);
  const [developerMode, setDeveloperMode] = useState<boolean>(loadDeveloperMode);
  const [folderPath, setFolderPath] = useState("");
  const [activeWorkspaceId, setActiveWorkspaceId] = useState<string | null>(
    () => loadRecentWorkspaces()[0]?.workspaceId ?? null,
  );
  const [starterSummary, setStarterSummary] = useState("No workspace indexed yet. Drop workspace path or type absolute folder path.");
  const [indexEvents, setIndexEvents] = useState<IndexEvent[]>([]);
  const [notebook, setNotebook] = useState<NotebookResponse>({ artifacts: [], file_count: 0, chunk_count: 0 });
  const [artifactFilter, setArtifactFilter] = useState("all");
  const [artifactSearch, setArtifactSearch] = useState("");
  const [artifactSort, setArtifactSort] = useState<"newest" | "oldest">("newest");
  const [artifactPreview, setArtifactPreview] = useState<ArtifactPreview | null>(null);
  const [pinnedArtifacts, setPinnedArtifacts] = useState<string[]>(readPinnedArtifacts);
  const [noteOverrides, setNoteOverrides] = useState<NoteOverrides>(() => readNoteOverrides(loadRecentWorkspaces()[0]?.workspaceId ?? null));
  const [sourceView, setSourceView] = useState<SourceViewState>({});
  const [developerSummary, setDeveloperSummary] = useState<BenchmarkSummary | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const [runtimeMode, setRuntimeMode] = useState<"live" | "fake" | null>(null);
  const [sourceSearch, setSourceSearch] = useState("");
  const [sourcePanelExpanded, setSourcePanelExpanded] = useState(true);
  const { startIndexStream } = useIndexStream();

  const activeWorkspace = recentWorkspaces.find((workspace) => workspace.workspaceId === activeWorkspaceId);
  const indexedDocumentCount = notebook.file_count;
  const lastIndexEntry = useMemo(
    () => indexHistory.find((entry) => entry.workspaceId === activeWorkspaceId),
    [activeWorkspaceId, indexHistory],
  );

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
    writeNoteOverrides(activeWorkspaceId, noteOverrides);
  }, [activeWorkspaceId, noteOverrides]);

  useEffect(() => {
    setNoteOverrides(readNoteOverrides(activeWorkspaceId));
  }, [activeWorkspaceId]);

  useEffect(() => {
    if (!activeWorkspaceId) {
      setNotebook({ artifacts: [], file_count: 0, chunk_count: 0 });
      return;
    }
    void getNotebook(activeWorkspaceId)
      .then(setNotebook)
      .catch((error: Error) => {
        setNotebook({ artifacts: [], file_count: 0, chunk_count: 0 });
        setErrorMessage(`Notebook load failed: ${error.message}`);
      });
  }, [activeWorkspaceId, setErrorMessage]);

  useEffect(() => {
    void getHealth()
      .then((health) => setRuntimeMode(health.mode))
      .catch(() => setRuntimeMode(null));
  }, []);

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
        Number(noteOverrides.pinnedIds.includes(right.id) || pinnedArtifacts.includes(right.id)) -
        Number(noteOverrides.pinnedIds.includes(left.id) || pinnedArtifacts.includes(left.id)),
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

  const activeWorkspaceHistory = indexHistory.filter((entry) => entry.workspaceId === activeWorkspaceId);
  const indexedPages = activeWorkspaceHistory.reduce((max, entry) => Math.max(max, entry.chunkCount ?? 0), 0);
  const fileTypeSummary = useMemo(() => {
    const extensions = recentWorkspaces
      .filter((workspace) => workspace.workspaceId === activeWorkspaceId)
      .flatMap((workspace) => workspace.folderPath.split(".").slice(1))
      .filter(Boolean);
    return extensions.length > 0 ? extensions.join(", ") : "mixed";
  }, [activeWorkspaceId, recentWorkspaces]);

  function updateWorkspaceRecord(workspaceId: string, update: Partial<StoredWorkspaceRecord>) {
    setRecentWorkspaces((current) =>
      current.map((item) => (item.workspaceId === workspaceId ? { ...item, ...update } : item)),
    );
  }

  async function loadNotebookForWorkspace(workspaceId: string) {
    try {
      const data = await getNotebook(workspaceId);
      setNotebook(data);
    } catch (error) {
      setErrorMessage(`Workspace not found: ${(error as Error).message}`);
      setNotebook({ artifacts: [], file_count: 0, chunk_count: 0 });
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

  function resetArtifactVisibility() {
    setArtifactFilter("all");
    setArtifactSearch("");
    setNoteOverrides((current) => ({
      ...current,
      hiddenIds: [],
    }));
    setStatusMessage("Artifact filters cleared.");
  }

  function clearActiveWorkspace() {
    if (!activeWorkspace || !window.confirm(`Clear workspace "${activeWorkspace.title}" from recent list?`)) {
      return;
    }
    setRecentWorkspaces((current) => current.filter((item) => item.workspaceId !== activeWorkspace.workspaceId));
    setIndexHistory((current) => current.filter((item) => item.workspaceId !== activeWorkspace.workspaceId));
    setActiveWorkspaceId((current) =>
      current === activeWorkspace.workspaceId
        ? recentWorkspaces.find((item) => item.workspaceId !== current)?.workspaceId ?? null
        : current,
    );
    setNotebook({ artifacts: [], file_count: 0, chunk_count: 0 });
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
    if (!force && activeWorkspace && activeWorkspace.folderPath === folder.trim() && !window.confirm("Re-index selected workspace?")) {
      return;
    }
    setBusy(true);
    setErrorMessage(null);
    setStatusMessage("Indexing workspace...");
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
    let indexedChunkCount: number | null = null;
    await startIndexStream(
      accepted.events,
      (event) => {
        setIndexEvents((current) => [...current, event]);
        if (event.event === "brief_ready") {
          setStarterSummary(event.brief.summary);
          const workspaceStatus = indexedChunkCount === 0 ? "empty" : "ready";
          updateWorkspaceRecord(accepted.workspace_id, {
            status: workspaceStatus,
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
          setStatusMessage(
            indexedChunkCount === 0
              ? "Workspace indexed, but no supported content produced searchable chunks."
              : "Workspace indexed.",
          );
          setBusy(false);
          void loadNotebookForWorkspace(accepted.workspace_id);
        }
        if (event.event === "index_complete") {
          indexedChunkCount = event.chunk_count;
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
      (error: Error) => {
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
      },
    );
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

  async function handleJumpToSource(anchor: string | undefined, citationIndex?: number) {
    if (!activeWorkspaceId || !anchor || !anchor.includes("#")) {
      return;
    }
    try {
      const [fileId, locator] = anchor.split("#");
      const response = await getSource(activeWorkspaceId, fileId, locator);
      setSourceView({ fileId, locator, response, citationIndex });
      setContextTab("sources");
      setContextPanelOpen(true);
      setRoute("source");
    } catch (error) {
      setErrorMessage(`Source open failed: ${(error as Error).message}`);
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

  function handleDropWorkspace(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragActive(false);
    const text = event.dataTransfer.getData("text/plain").trim();
    const filePath =
      text ||
      Array.from(event.dataTransfer.files)
        .map((file) => {
          const candidate = file as File & { path?: string; webkitRelativePath?: string };
          return candidate.path ?? candidate.webkitRelativePath;
        })
        .find(Boolean) ||
      "";
    if (filePath) {
      setFolderPath(filePath);
      setStatusMessage("Workspace path loaded.");
    }
  }

  const noBackend = runtimeMode === null;

  return {
    recentWorkspaces,
    setRecentWorkspaces,
    indexHistory,
    setIndexHistory,
    developerMode,
    setDeveloperMode,
    folderPath,
    setFolderPath,
    activeWorkspaceId,
    setActiveWorkspaceId,
    activeWorkspace,
    starterSummary,
    setStarterSummary,
    indexEvents,
    setIndexEvents,
    notebook,
    setNotebook,
    artifactFilter,
    setArtifactFilter,
    artifactSearch,
    setArtifactSearch,
    artifactSort,
    setArtifactSort,
    artifactPreview,
    pinnedArtifacts,
    setPinnedArtifacts,
    noteOverrides,
    setNoteOverrides,
    sourceView,
    setSourceView,
    developerSummary,
    dragActive,
    setDragActive,
    runtimeMode,
    sourceSearch,
    setSourceSearch,
    sourcePanelExpanded,
    setSourcePanelExpanded,
    indexedDocumentCount,
    lastIndexEntry,
    filteredArtifacts,
    sourceSearchResults,
    indexedPages,
    fileTypeSummary,
    noBackend,
    loadNotebookForWorkspace,
    handleIndex,
    handleOpenArtifact,
    handleJumpToSource,
    handleBenchmarkImport,
    handleDropWorkspace,
    renameArtifact,
    deleteArtifact,
    resetArtifactVisibility,
    clearActiveWorkspace,
    updateWorkspaceRecord,
  };
}
