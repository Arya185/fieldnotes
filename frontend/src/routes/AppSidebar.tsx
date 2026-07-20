import type { DragEventHandler } from "react";

import { LockBadge } from "../components/LockBadge";
import type { IndexHistoryEntry, StoredWorkspaceRecord } from "../lib/storage";

interface AppSidebarProps {
  sidebarCollapsed: boolean;
  developerMode: boolean;
  runtimeMode: "live" | "fake" | null;
  dragActive: boolean;
  activeWorkspace: StoredWorkspaceRecord | undefined;
  folderPath: string;
  starterSummary: string;
  recentWorkspaces: StoredWorkspaceRecord[];
  activeWorkspaceId: string | null;
  indexHistory: IndexHistoryEntry[];
  busy: boolean;
  onToggleSidebar: () => void;
  onSetFolderPath: (value: string) => void;
  onSetDragActive: (active: boolean) => void;
  onDropWorkspace: DragEventHandler<HTMLDivElement>;
  onIndexWorkspace: () => void;
  onReindexWorkspace: () => void;
  onClearWorkspace: () => void;
  onToggleDeveloperMode: () => void;
  onSelectWorkspace: (workspaceId: string) => void;
  formatDateTime: (value?: string) => string;
  formatRelative: (value?: string) => string;
}

export function AppSidebar({
  sidebarCollapsed,
  developerMode,
  runtimeMode,
  dragActive,
  activeWorkspace,
  folderPath,
  starterSummary,
  recentWorkspaces,
  activeWorkspaceId,
  indexHistory,
  busy,
  onToggleSidebar,
  onSetFolderPath,
  onSetDragActive,
  onDropWorkspace,
  onIndexWorkspace,
  onReindexWorkspace,
  onClearWorkspace,
  onToggleDeveloperMode,
  onSelectWorkspace,
  formatDateTime,
  formatRelative,
}: AppSidebarProps) {
  return (
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
              onClick={onToggleSidebar}
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
          onSetDragActive(true);
        }}
        onDragLeave={() => onSetDragActive(false)}
        onDrop={onDropWorkspace}
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
          onChange={(event) => onSetFolderPath(event.target.value)}
        />
        {!sidebarCollapsed && (
          <p className="muted">
            Drag folder path here where browser supports it. Absolute path only.
          </p>
        )}
        <div className="toolbar compact">
          <button className="button" onClick={onIndexWorkspace} disabled={busy}>
            {sidebarCollapsed ? "Index" : "Index Workspace"}
          </button>
          <button className="button secondary" onClick={onReindexWorkspace} disabled={!activeWorkspace || busy}>
            {sidebarCollapsed ? "Retry" : "Re-index"}
          </button>
          {!sidebarCollapsed && (
            <button className="button ghost" onClick={onClearWorkspace} disabled={!activeWorkspace}>
              Clear Workspace
            </button>
          )}
        </div>
        {!sidebarCollapsed && <p className="muted">{starterSummary}</p>}
        {!sidebarCollapsed && !activeWorkspace && (
          <div className="hint-card">Start by choosing workspace, indexing it, then asking grounded questions.</div>
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
            onClick={onToggleDeveloperMode}
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
              onClick={() => onSelectWorkspace(workspace.workspaceId)}
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
  );
}
