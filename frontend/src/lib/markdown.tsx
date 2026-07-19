import React from "react";

function renderInline(text: string, keyPrefix: string): React.ReactNode[] {
  const nodes: React.ReactNode[] = [];
  const parts = text.split(/(`[^`]+`)/g);
  parts.forEach((part, index) => {
    if (!part) {
      return;
    }
    if (part.startsWith("`") && part.endsWith("`")) {
      nodes.push(
        <code className="inline" key={`${keyPrefix}-${index}`}>
          {part.slice(1, -1)}
        </code>,
      );
      return;
    }
    nodes.push(part);
  });
  return nodes;
}

export function MarkdownBlock({ text }: { text: string }) {
  const blocks = text.split(/```/g);
  return (
    <div className="message-body">
      {blocks.map((block, index) => {
        if (index % 2 === 1) {
          return <pre key={`code-${index}`}>{block.trim()}</pre>;
        }
        return block
          .split(/\n{2,}/g)
          .filter(Boolean)
          .map((paragraph, paragraphIndex) => (
            <p key={`p-${index}-${paragraphIndex}`}>
              {renderInline(paragraph, `${index}-${paragraphIndex}`)}
            </p>
          ));
      })}
    </div>
  );
}
