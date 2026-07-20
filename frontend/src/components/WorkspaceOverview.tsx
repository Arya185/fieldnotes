import type { IndexHistoryEntry, StoredWorkspaceRecord } from "../lib/storage";
import type { IndexEvent } from "../types";
import { EmptyState } from "./EmptyState";

interface WorkspaceOverviewProps {
  activeWorkspace?: StoredWorkspaceRecord;
  starterSummary: string;
  indexedDocumentCount: number;
  indexedPages: number;
  lastIndexEntry?: IndexHistoryEntry;
  fileTypeSummary: string;
  indexEvents: IndexEvent[];
  runtimeMode: "live" | "fake" | null;
  busy: boolean;
  noBackend: boolean;
  formatDateTime: (value?: string) => string;
  formatRelative: (value?: string) => string;
}

export function WorkspaceOverview({
  activeWorkspace,
  starterSummary,
  indexedDocumentCount,
  indexedPages,
  lastIndexEntry,
  fileTypeSummary,
  indexEvents,
  runtimeMode,
  busy,
  noBackend,
  formatDateTime,
  formatRelative,
}: WorkspaceOverviewProps) {
  return (
    <section className="workspace-overview stack">
      <div className="hero-card">
        <div className="eyebrow">Workspace Library</div>
        <h2>{activeWorkspace?.title ?? "Choose a workspace"}</h2>
        <p className="hero-copy">
          {activeWorkspace
            ? starterSummary
            : "Index a local folder to start reading, asking grounded questions, and studying from your sources."}
        </p>
        <div className="hero-metrics">
          <div className="metric-card"><span className="metric-label">Documents</span><strong>{indexedDocumentCount}</strong></div>
          <div className="metric-card"><span className="metric-label">Status</span><strong>{activeWorkspace?.status ?? "idle"}</strong></div>
          <div className="metric-card"><span className="metric-label">Last indexed</span><strong>{formatRelative(activeWorkspace?.lastIndexedAt)}</strong></div>
          <div className="metric-card"><span className="metric-label">Indexed pages</span><strong>{indexedPages}</strong></div>
        </div>
      </div>

      {runtimeMode === "fake" && <div className="hint-card status-callout">Fake mode startup active. Retrieval real, answers deterministic, no OpenAI call required. Add live key in `.env` when ready.</div>}
      {!activeWorkspace && <EmptyState title="No workspace selected" body="Pick local folder, then index it. Recent workspaces stay in left rail for quick return." />}

      <div className="content-grid">
        <article className="workspace-pane">
          <div className="section-heading"><div><div className="eyebrow">Current Folder</div><h3>Document library</h3></div><span className="pill">{activeWorkspace?.status ?? "none"}</span></div>
          <div className="doc-library-card">
            <div className="doc-library-icon" aria-hidden="true">📁</div>
            <div>
              <strong>{activeWorkspace?.title ?? "No folder selected"}</strong>
              <p className="muted">{indexedDocumentCount} indexed documents{lastIndexEntry?.chunkCount !== undefined ? ` · ${lastIndexEntry.chunkCount} chunks` : ""}</p>
              <p className="muted">{activeWorkspace?.folderPath ? `Folder: ${activeWorkspace.folderPath}` : "Indexing history will appear here."}</p>
              <p className="muted">{activeWorkspace?.lastIndexedAt ? `Last indexed ${formatDateTime(activeWorkspace.lastIndexedAt)}` : "Waiting for first successful index run."}</p>
              <p className="muted">File types: {fileTypeSummary}</p>
            </div>
          </div>
        </article>
        <article className="workspace-pane">
          <div className="section-heading"><div><div className="eyebrow">Index Progress</div><h3>Latest run</h3></div></div>
          <ul className="progress-list polished">
            {indexEvents.length === 0 && <li>No active indexing run.</li>}
            {indexEvents.map((event, index) => <li key={`${event.event}-${index}`}>
              {event.event === "file_started" && `Started ${event.display_name}`}
              {event.event === "file_parsed" && `${event.display_name}: ${event.parse_summary}`}
              {event.event === "index_complete" && `Indexed ${event.file_count} files, ${event.chunk_count} chunks`}
              {event.event === "brief_ready" && event.brief.summary}
            </li>)}
          </ul>
        </article>
      </div>

      {activeWorkspace?.status === "error" && <div className="hint-card">Index failed. Review the folder path, then retry the same workspace or choose a different folder.</div>}
      {busy && activeWorkspace && <div className="hint-card status-callout">Indexing in progress. Keep workspace open. Progress stream updates below and notes appear when run completes.</div>}
      {noBackend && <EmptyState title="Backend unavailable" body="Frontend loaded, backend did not answer health check. Start backend, then refresh workspace." />}
    </section>
  );
}
