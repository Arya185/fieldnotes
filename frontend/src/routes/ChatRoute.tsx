import { MarkdownBlock } from "../lib/markdown";
import type { ChatMessage, SourceAccordionState, SourceViewState } from "../lib/appState/types";
import type { ArtifactCard, CitationChip } from "../types";

interface ChatRouteProps {
  busy: boolean;
  chatMessages: ChatMessage[];
  allSourcesExpanded: boolean;
  sourceAccordionState: SourceAccordionState;
  sourceView: SourceViewState;
  onRetryLast: () => void;
  onRegenerate: () => void;
  onCancel: () => void;
  onExportConversation: () => void;
  onSetChatInput: (value: string) => void;
  onCopyAnswer: (message: ChatMessage) => void;
  onRequestAnswer: (question: string) => void;
  onOpenArtifact: (artifact: ArtifactCard) => void;
  onJumpToSource: (anchor: string | undefined) => void;
  onCopyCitation: (chip: CitationChip) => void;
  onToggleAccordion: (messageId: string, open: boolean) => void;
  onToggleAllSources: () => void;
}

export function ChatRoute({
  busy,
  chatMessages,
  allSourcesExpanded,
  sourceAccordionState,
  sourceView,
  onRetryLast,
  onRegenerate,
  onCancel,
  onExportConversation,
  onSetChatInput,
  onCopyAnswer,
  onRequestAnswer,
  onOpenArtifact,
  onJumpToSource,
  onCopyCitation,
  onToggleAccordion,
  onToggleAllSources,
}: ChatRouteProps) {
  return (
    <section className="chat-layout">
      <div className="chat-toolbar">
        <button className="button secondary" onClick={onRetryLast} disabled={busy || chatMessages.length === 0}>
          Retry Last
        </button>
        <button className="button secondary" onClick={onRegenerate} disabled={busy || chatMessages.length === 0}>
          Regenerate
        </button>
        <button className="button ghost" onClick={onCancel} disabled={!busy}>
          Cancel
        </button>
        <button className="button ghost" onClick={onExportConversation} disabled={chatMessages.length === 0}>
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
            <button className="suggestion-chip" onClick={() => onSetChatInput("Summarize the main ideas in this workspace.")}>
              Summarize this workspace
            </button>
            <button className="suggestion-chip" onClick={() => onSetChatInput("List the most important documents to read first.")}>
              What should I read first?
            </button>
            <button className="suggestion-chip" onClick={() => onSetChatInput("Create a study guide from the indexed sources.")}>
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
              <button className="button secondary" onClick={() => onCopyAnswer(message)} disabled={!message.text}>
                Copy Answer
              </button>
              {message.requestText && (
                <button className="button ghost" onClick={() => onRequestAnswer(message.requestText!)} disabled={busy}>
                  Regenerate
                </button>
              )}
            </div>
          )}
          {message.artifacts.length > 0 && (
            <div className="stack">
              {message.artifacts.map((artifact) => (
                <div className="artifact-preview" key={`${message.id}-${artifact.artifact_id}-${artifact.title}`}>
                  <div className="artifact-preview-badge" aria-label="Saved to Notebook">
                    <span aria-hidden="true">📝</span>
                    <span>Saved to Notebook</span>
                  </div>
                  <div className="split-row">
                    <strong>{artifact.title || artifact.kind}</strong>
                    <button
                      className="button secondary"
                      onClick={() =>
                        onOpenArtifact({
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
              onToggle={(event) => onToggleAccordion(message.id, (event.currentTarget as HTMLDetailsElement).open)}
            >
              <summary>Sources ({message.citations.length})</summary>
              <div className="sources-list">
                {message.citations.map((chip, index) => (
                  <div className="source-row" key={`${message.id}-citation-${index}`}>
                    <button
                      className={`source-link ${sourceView.locator && chip.anchor?.endsWith(sourceView.locator) ? "source-link-active" : ""}`}
                      onClick={() => onJumpToSource(chip.anchor)}
                    >
                      {chip.label}
                    </button>
                    <button className="mini-action" aria-label={`Copy citation ${chip.label}`} onClick={() => onCopyCitation(chip)}>
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
          <button className="button ghost" onClick={onToggleAllSources}>
            {allSourcesExpanded ? "Collapse All Sources" : "Expand All Sources"}
          </button>
          <span className="muted">Shortcuts: Cmd/Ctrl+Enter send, Cmd/Ctrl+K focus, Escape stop.</span>
        </div>
      )}
    </section>
  );
}
