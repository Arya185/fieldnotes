import type {
  ContextTab,
  NoteOverrides,
  QuizReviewItem,
  QuizState,
  SourceNavItem,
  SourceViewState,
} from "../lib/appState/types";
import type { ArtifactCard, NotebookResponse } from "../types";

interface ContextPanelRouteProps {
  contextPanelOpen: boolean;
  contextTab: ContextTab;
  activeWorkspaceTitle?: string;
  notebook: NotebookResponse;
  sourceView: SourceViewState;
  sourceNavItems: SourceNavItem[];
  filteredArtifacts: ArtifactCard[];
  noteOverrides: NoteOverrides;
  pinnedArtifacts: string[];
  quizState: QuizState;
  reviewItems: QuizReviewItem[];
  onTogglePanel: () => void;
  onSetContextTab: (tab: ContextTab) => void;
  onOpenSourceAnchor: (anchor: string | undefined) => void;
  onOpenArtifact: (artifact: ArtifactCard) => void;
  onResetArtifactVisibility: () => void;
}

export function ContextPanelRoute({
  contextPanelOpen,
  contextTab,
  activeWorkspaceTitle,
  notebook,
  sourceView,
  sourceNavItems,
  filteredArtifacts,
  noteOverrides,
  pinnedArtifacts,
  quizState,
  reviewItems,
  onTogglePanel,
  onSetContextTab,
  onOpenSourceAnchor,
  onOpenArtifact,
  onResetArtifactVisibility,
}: ContextPanelRouteProps) {
  return (
    <aside className="rightbar panel">
      <section className="section context-header">
        {contextPanelOpen ? (
          <div className="split-row">
            <div>
              <div className="eyebrow">Context Panel</div>
              <strong>Sources, notebook, study</strong>
            </div>
            <button
              className="icon-button"
              onClick={onTogglePanel}
              aria-label="Collapse context panel"
            >
              ›
            </button>
          </div>
        ) : (
          <div className="context-rail">
            <button
              className="icon-button"
              onClick={onTogglePanel}
              aria-label="Expand context panel"
            >
              ‹
            </button>
            <div className="context-rail-label">
              <span className="eyebrow">Context</span>
              <strong>Panel</strong>
            </div>
            <div className="context-rail-tabs" aria-hidden="true">
              <span className="context-rail-pill">S</span>
              <span className="context-rail-pill">N</span>
              <span className="context-rail-pill">Q</span>
            </div>
          </div>
        )}
      </section>

      {contextPanelOpen && (
        <>
          <section className="section context-tabs">
            <button className="tab" aria-selected={contextTab === "sources"} onClick={() => onSetContextTab("sources")}>
              Sources
            </button>
            <button className="tab" aria-selected={contextTab === "notebook"} onClick={() => onSetContextTab("notebook")}>
              Notebook
            </button>
            <button className="tab" aria-selected={contextTab === "quiz"} onClick={() => onSetContextTab("quiz")}>
              Quiz
            </button>
          </section>

          <section className="section">
            <strong>Workspace Status</strong>
            <div className="grid-two">
              <div className="workspace-card">
                <div className="muted">Workspace</div>
                <strong>{activeWorkspaceTitle ?? "None"}</strong>
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
                  <p className="muted">Open full source view in center panel for highlighted passage text.</p>
                </article>
              ) : (
                <div className="hint-card">Open source from citation chip. Context panel keeps quick trail while center view shows full passage.</div>
              )}
              <div className="stack">
                {sourceNavItems.map((item, index) => (
                  <button
                    className={`source-link source-nav-link ${sourceView.citationIndex === index ? "source-link-active" : ""}`}
                    key={`${item.label}-${index}`}
                    onClick={() => onOpenSourceAnchor(item.anchor)}
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
              {notebook.artifacts.length === 0 ? (
                <div className="hint-card">No notebook entries yet. Ask question or finish quiz to collect study artifacts.</div>
              ) : filteredArtifacts.length === 0 ? (
                <div className="hint-card">
                  {notebook.artifacts.length} artifact(s) hidden or filtered out.
                  <div className="toolbar compact">
                    <button className="button secondary" onClick={onResetArtifactVisibility}>
                      Clear Filters
                    </button>
                  </div>
                </div>
              ) : (
                <div className="artifact-list">
                  {filteredArtifacts.slice(0, 4).map((artifact) => (
                    <button className="artifact-card notebook-card" key={artifact.id} onClick={() => onOpenArtifact(artifact)}>
                      <header>
                        <strong>{noteOverrides.renamedTitles[artifact.id] ?? artifact.title}</strong>
                        <span className="pill">{noteOverrides.pinnedIds.includes(artifact.id) || pinnedArtifacts.includes(artifact.id) ? "pinned" : artifact.kind}</span>
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
                <div className="hint-card">Start quiz to track progress here.</div>
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
  );
}
