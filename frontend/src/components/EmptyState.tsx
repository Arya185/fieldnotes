import type { MouseEventHandler } from "react";

interface EmptyStateProps {
  title: string;
  body: string;
  actionLabel?: string;
  onAction?: MouseEventHandler<HTMLButtonElement>;
}

export function EmptyState({ title, body, actionLabel, onAction }: EmptyStateProps) {
  return (
    <div className="empty-panel">
      <div className="eyebrow">Next Step</div>
      <h3>{title}</h3>
      <p>{body}</p>
      {actionLabel && onAction && (
        <button className="button secondary" onClick={onAction}>
          {actionLabel}
        </button>
      )}
    </div>
  );
}
