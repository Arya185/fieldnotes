import { EmptyState } from "../components/EmptyState";
import { MarkdownBlock } from "../lib/markdown";
import type { ArtifactPreview, NoteOverrides } from "../lib/appState/types";
import type { ArtifactCard, NotebookResponse } from "../types";

interface NotebookRouteProps {
  notebook: NotebookResponse;
  artifactFilter: string;
  artifactSearch: string;
  artifactSort: "newest" | "oldest";
  filteredArtifacts: ArtifactCard[];
  artifactPreview: ArtifactPreview | null;
  noteOverrides: NoteOverrides;
  pinnedArtifacts: string[];
  formatDateTime: (value?: string) => string;
  onSetArtifactFilter: (value: string) => void;
  onSetArtifactSearch: (value: string) => void;
  onSetArtifactSort: (value: "newest" | "oldest") => void;
  onGoToChat: () => void;
  onOpenArtifact: (artifact: ArtifactCard) => void;
  onTogglePin: (artifactId: string) => void;
  onRenameArtifact: (artifact: ArtifactCard) => void;
  onExportArtifact: (artifact: ArtifactCard) => void;
  onAskWithArtifact: (artifact: ArtifactCard) => void;
  onDeleteArtifact: (artifact: ArtifactCard) => void;
}

export function NotebookRoute({
  notebook,
  artifactFilter,
  artifactSearch,
  artifactSort,
  filteredArtifacts,
  artifactPreview,
  noteOverrides,
  pinnedArtifacts,
  formatDateTime,
  onSetArtifactFilter,
  onSetArtifactSearch,
  onSetArtifactSort,
  onGoToChat,
  onOpenArtifact,
  onTogglePin,
  onRenameArtifact,
  onExportArtifact,
  onAskWithArtifact,
  onDeleteArtifact,
}: NotebookRouteProps) {
  return (
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
            onClick={() => onSetArtifactFilter(kind)}
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
          onChange={(event) => onSetArtifactSearch(event.target.value)}
        />
        <select
          aria-label="Sort artifacts"
          className="select"
          value={artifactSort}
          onChange={(event) => onSetArtifactSort(event.target.value as "newest" | "oldest")}
        >
          <option value="newest">Newest</option>
          <option value="oldest">Oldest</option>
        </select>
      </div>
      {notebook.artifacts.length === 0 && (
        <EmptyState
          title="No notebook entries"
          body="Artifacts appear after answers, quizzes, or analysis runs. Ask workspace question to start collecting reusable notes."
          actionLabel="Go To Chat"
          onAction={onGoToChat}
        />
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
                <button className="button secondary" onClick={() => onOpenArtifact(artifact)}>
                  Reopen
                </button>
                <button className="button ghost" onClick={() => onTogglePin(artifact.id)}>
                  {pinnedArtifacts.includes(artifact.id) ? "Unpin" : "Pin"}
                </button>
                <button className="button ghost" onClick={() => onRenameArtifact(artifact)}>
                  Rename
                </button>
                <button className="button ghost" onClick={() => onExportArtifact(artifact)}>
                  Export
                </button>
                <button className="button ghost" onClick={() => onAskWithArtifact(artifact)}>
                  Ask With
                </button>
                <button className="button ghost" onClick={() => onDeleteArtifact(artifact)}>
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
  );
}
