import type { ChatMessage } from "../lib/appState/types";
import type { BenchmarkSummary } from "../types";

interface DeveloperRouteProps {
  chatMessages: ChatMessage[];
  developerChunks: Array<{ label: string; chunk: string }>;
  developerSummary: BenchmarkSummary | null;
  onBenchmarkImport: (file: File | null) => void;
}

export function DeveloperRoute({
  chatMessages,
  developerChunks,
  developerSummary,
  onBenchmarkImport,
}: DeveloperRouteProps) {
  return (
    <section className="developer-grid">
      <article className="dev-card">
        <header>
          <strong>Retrieval Transparency</strong>
          <input
            aria-label="Load benchmark summary"
            className="input"
            type="file"
            accept="application/json"
            onChange={(event) => onBenchmarkImport(event.target.files?.[0] ?? null)}
          />
        </header>
        <div className="stack">
          <div className="history-card">
            <strong>Live Trace Timeline</strong>
            {chatMessages.flatMap((message) => message.steps).map((step, index) => (
              <div className="timeline-row" key={`${step}-${index}`}>
                <span className="pill">{index + 1}</span>
                <span>{step}</span>
              </div>
            ))}
          </div>
          <div className="history-card">
            <strong>Planner Execution Graph</strong>
            {chatMessages.flatMap((message) => message.steps).map((step, index) => (
              <div key={`${step}-graph-${index}`}>{index === 0 ? "start" : "↓"} {step}</div>
            ))}
          </div>
          <div className="history-card">
            <strong>Final Grounded Chunks</strong>
            {developerChunks.length > 0 ? (
              developerChunks.map((chunk, index) => (
                <div key={`${chunk.label}-${index}`}>
                  <strong>{chunk.label}</strong>
                  <p>{chunk.chunk}</p>
                </div>
              ))
            ) : (
              <p className="muted">Current backend transport exposes only final cited chunks.</p>
            )}
          </div>
        </div>
      </article>

      <article className="dev-card">
        <strong>Observability</strong>
        {developerSummary ? (
          <div className="stack">
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Metric</th>
                    <th>Avg</th>
                    <th>Max</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(developerSummary.latency_summary).map(([key, value]) => (
                    <tr key={key}>
                      <td>{key}</td>
                      <td>{value.avg.toFixed(2)}</td>
                      <td>{value.max.toFixed(2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="history-card">
              <strong>Latency Charts</strong>
              {Object.entries(developerSummary.latency_summary).map(([key, value]) => (
                <div className="progress-meter" key={`lat-${key}`}>
                  <span>{key}</span>
                  <div className="meter-bar">
                    <div className="meter-fill accent" style={{ width: `${Math.min(100, value.avg)}%` }} />
                  </div>
                </div>
              ))}
            </div>
            <div className="history-card">
              <strong>Retrieval Score Breakdown</strong>
              <pre>{JSON.stringify(developerSummary.retrieval_metrics, null, 2)}</pre>
            </div>
            <div className="history-card">
              <strong>Reranking Decisions</strong>
              <pre>{JSON.stringify(developerSummary.regression_comparison ?? {}, null, 2)}</pre>
            </div>
            <div className="history-card">
              <strong>Execution Metrics</strong>
              <pre>{JSON.stringify(developerSummary.execution_metrics, null, 2)}</pre>
            </div>
          </div>
        ) : (
          <p className="muted">
            Import benchmark JSON from `scripts/benchmarks_latest.json` to inspect traces, latencies, benchmark summaries.
          </p>
        )}
      </article>
    </section>
  );
}
