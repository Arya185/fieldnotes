interface ModeBadgeProps {
  mode: "live" | "fake" | null;
}

export function ModeBadge({ mode }: ModeBadgeProps) {
  if (mode === "live") {
    return <span className="pill success">Live OpenAI</span>;
  }
  if (mode === "fake") {
    return <span className="pill">Fake LLM</span>;
  }
  return <span className="pill">Backend Pending</span>;
}
