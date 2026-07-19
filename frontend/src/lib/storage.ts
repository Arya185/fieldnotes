export interface StoredWorkspaceRecord {
  workspaceId: string;
  folderPath: string;
  title: string;
  lastIndexedAt?: string;
  lastRunId?: string;
  status: "idle" | "indexing" | "ready" | "error";
}

export interface IndexHistoryEntry {
  runId: string;
  workspaceId: string;
  startedAt: string;
  finishedAt?: string;
  fileCount?: number;
  chunkCount?: number;
  status: "accepted" | "running" | "completed" | "failed";
}

const WORKSPACES_KEY = "fieldnotes.workspaces";
const HISTORY_KEY = "fieldnotes.indexHistory";
const DEV_MODE_KEY = "fieldnotes.devMode";

function readJson<T>(key: string, fallback: T): T {
  if (typeof window === "undefined") {
    return fallback;
  }
  const raw = window.localStorage.getItem(key);
  if (!raw) {
    return fallback;
  }
  try {
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

function writeJson<T>(key: string, value: T): void {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.setItem(key, JSON.stringify(value));
}

export function loadRecentWorkspaces(): StoredWorkspaceRecord[] {
  return readJson<StoredWorkspaceRecord[]>(WORKSPACES_KEY, []);
}

export function saveRecentWorkspaces(workspaces: StoredWorkspaceRecord[]): void {
  writeJson(WORKSPACES_KEY, workspaces);
}

export function loadIndexHistory(): IndexHistoryEntry[] {
  return readJson<IndexHistoryEntry[]>(HISTORY_KEY, []);
}

export function saveIndexHistory(entries: IndexHistoryEntry[]): void {
  writeJson(HISTORY_KEY, entries);
}

export function loadDeveloperMode(): boolean {
  return readJson<boolean>(DEV_MODE_KEY, false);
}

export function saveDeveloperMode(enabled: boolean): void {
  writeJson(DEV_MODE_KEY, enabled);
}
