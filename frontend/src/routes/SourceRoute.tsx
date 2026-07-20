import { EmptyState } from "../components/EmptyState";
import type { SourceViewState } from "../lib/appState/types";

interface SourceRouteProps {
  allCitationsCount: number;
  sourceView: SourceViewState;
  sourceSearch: string;
  sourceSearchResults: number[];
  sourcePanelExpanded: boolean;
  quizSourceAnchor?: string;
  onOpenQuizCitation: () => void;
  onSourceNav: (direction: -1 | 1) => void;
  onCopySourceRef: () => void;
  onToggleExpanded: () => void;
  onSetSourceSearch: (value: string) => void;
}

export function SourceRoute({
  allCitationsCount,
  sourceView,
  sourceSearch,
  sourceSearchResults,
  sourcePanelExpanded,
  quizSourceAnchor,
  onOpenQuizCitation,
  onSourceNav,
  onCopySourceRef,
  onToggleExpanded,
  onSetSourceSearch,
}: SourceRouteProps) {
  return (
    <section className="workspace-overview stack">
      <div className="section-heading">
        <div>
          <div className="eyebrow">Source</div>
          <h3>Grounding view</h3>
        </div>
      </div>
      <div className="toolbar">
        <button className="button secondary" onClick={onOpenQuizCitation} disabled={!quizSourceAnchor}>
          Open Quiz Citation
        </button>
        <button className="button secondary" onClick={() => onSourceNav(-1)} disabled={sourceView.citationIndex === undefined || sourceView.citationIndex < 1}>
          Previous Citation
        </button>
        <button className="button secondary" onClick={() => onSourceNav(1)} disabled={sourceView.citationIndex === undefined || sourceView.citationIndex >= allCitationsCount - 1}>
          Next Citation
        </button>
        <button className="button ghost" onClick={onCopySourceRef} disabled={!sourceView.response}>
          Copy Source Ref
        </button>
        <button className="button ghost" onClick={onToggleExpanded} disabled={!sourceView.response}>
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
              onChange={(event) => onSetSourceSearch(event.target.value)}
            />
            <span className="pill">Page {sourceView.locator?.split("/")[0] ?? "current"}</span>
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
        <EmptyState
          title="No source selected"
          body="Open citation from chat or quiz. Fieldnotes will jump straight to cited passage and keep locator visible."
        />
      )}
    </section>
  );
}
