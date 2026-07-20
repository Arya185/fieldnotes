import type { RefObject } from "react";

interface ComposerProps {
  value: string;
  inputRef: RefObject<HTMLTextAreaElement | null>;
  activeWorkspaceId: string | null;
  busy: boolean;
  onChange: (value: string) => void;
  onSubmit: () => void;
  onCancel: () => void;
}

export function Composer({ value, inputRef, activeWorkspaceId, busy, onChange, onSubmit, onCancel }: ComposerProps) {
  return (
    <footer className="composer elevated-composer">
      <textarea
        aria-label="Ask Fieldnotes"
        className="textarea"
        placeholder="Ask grounded question..."
        value={value}
        ref={inputRef}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={(event) => {
          if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
            event.preventDefault();
            onSubmit();
          }
        }}
      />
      <div className="toolbar">
        <button className="button" onClick={onSubmit} disabled={!activeWorkspaceId || busy}>
          Send
        </button>
        <button className="button secondary" onClick={onCancel} disabled={!busy}>
          Stop Generating
        </button>
        <span className="muted">Ctrl/Cmd+Enter send. Ctrl/Cmd+K focus. Escape stop. Shift+Cmd/Ctrl+R retry.</span>
      </div>
    </footer>
  );
}
