import React, { useEffect, useState } from "react";
import { getStudyProgress, completePlanItem } from "../lib/api";

function ProgressRing({ size = 96, stroke = 10, value = 0 }: { size?: number; stroke?: number; value: number }) {
  const radius = (size - stroke) / 2;
  const circ = 2 * Math.PI * radius;
  const filled = Math.max(0, Math.min(1, value));
  const dash = filled * circ;
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
      <g transform={`translate(${size / 2},${size / 2})`}>
        <circle r={radius} stroke="#eee" strokeWidth={stroke} fill="none" />
        <circle
          r={radius}
          stroke="#4f46e5"
          strokeWidth={stroke}
          strokeLinecap="round"
          fill="none"
          strokeDasharray={`${dash} ${circ - dash}`}
          transform="rotate(-90)"
        />
        <text x="0" y="4" textAnchor="middle" fontSize={14} fill="#111">
          {Math.round(filled * 100)}%
        </text>
      </g>
    </svg>
  );
}

function MasteryBar({ value }: { value: number }) {
  const pct = Math.round(Math.max(0, Math.min(1, value)) * 100);
  const color = value >= 0.8 ? "#10b981" : value >= 0.6 ? "#f59e0b" : "#ef4444";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <div style={{ flex: 1, background: "#f3f4f6", height: 12, borderRadius: 6, overflow: "hidden" }}>
        <div style={{ width: `${pct}%`, height: 12, background: color }} />
      </div>
      <div style={{ width: 40, textAlign: "right" }}>{pct}%</div>
    </div>
  );
}

export function StudyProgressRoute(props: { activeWorkspaceId?: string | null }) {
  const [progress, setProgress] = useState<any | null>(null);
  const [loading, setLoading] = useState(false);
  const [selectedTopic, setSelectedTopic] = useState<any | null>(null);

  useEffect(() => {
    async function load() {
      if (!props.activeWorkspaceId) return;
      setLoading(true);
      try {
        const data = await getStudyProgress(props.activeWorkspaceId);
        setProgress(data);
      } catch (err) {
        console.error(err);
      } finally {
        setLoading(false);
      }
    }
    void load();
  }, [props.activeWorkspaceId]);

  if (!props.activeWorkspaceId) return <div>Select a workspace to view progress.</div>;

  return (
    <div className="study-progress" style={{ padding: 16 }}>
      <h3>Study Progress Dashboard</h3>
      {loading && <p>Loading...</p>}
      {!loading && progress && (
        <div style={{ display: "grid", gridTemplateColumns: "240px 1fr", gap: 20 }}>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              <ProgressRing value={progress.estimated_exam_readiness ?? 0} />
              <div>
                <div style={{ fontSize: 18, fontWeight: 600 }}>{Math.round((progress.avg_mastery ?? 0) * 100)}% mastery</div>
                <div style={{ color: "#6b7280" }}>Streak: {progress.study_streak} days</div>
                <div style={{ color: "#6b7280" }}>Overall completion: {Math.round((progress.overall_completion ?? 0) * 100)}%</div>
              </div>
            </div>

            <section style={{ marginTop: 16 }}>
              <h4 style={{ marginBottom: 8 }}>Weak topics</h4>
              <ul>
                {Array.isArray(progress.weak_topics) && progress.weak_topics.slice(0, 8).map((t: any) => (
                  <li key={t.id} style={{ cursor: "pointer" }} onClick={() => setSelectedTopic(t)}>{t.topic} — {(t.mastery_score * 100).toFixed(0)}%</li>
                ))}
              </ul>
            </section>
          </div>

          <div>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <h4>Today's tasks</h4>
              <div style={{ color: "#6b7280" }}>{(progress.todays_tasks || []).length} tasks</div>
            </div>
            <div>
              <ul>
                {Array.isArray(progress.todays_tasks) && progress.todays_tasks.map((it: any) => (
                  <li key={it.id} style={{ marginBottom: 6, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <div>
                      <strong>{it.task_type}</strong> — {it.date} — <em>{it.topic_id}</em>
                    </div>
                    <div>
                      <button className="button small" onClick={async () => {
                        try {
                          let score: number | undefined = undefined;
                          if (it.task_type === "quiz") {
                            const raw = prompt("Enter quiz score percentage (0-100):", "100");
                            if (raw !== null) {
                              const pct = Number(raw);
                              if (!Number.isNaN(pct)) score = Math.max(0, Math.min(100, pct)) / 100.0;
                            }
                          }
                          await completePlanItem(props.activeWorkspaceId!, it.plan_id, it.id, score);
                          // refresh
                          const data = await getStudyProgress(props.activeWorkspaceId!);
                          setProgress(data);
                        } catch (err) {
                          alert(String(err));
                        }
                      }}>Mark done</button>
                    </div>
                  </li>
                ))}
              </ul>
            </div>

            <h4 style={{ marginTop: 12 }}>Upcoming reviews</h4>
            <div>
              <ul>
                {Array.isArray(progress.upcoming_reviews) && progress.upcoming_reviews.map((it: any) => (
                  <li key={it.id} style={{ marginBottom: 6, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <div>
                      <strong>{it.task_type}</strong> — {it.date} — <em>{it.topic_id}</em>
                    </div>
                    <div>
                      <button className="button small" onClick={async () => {
                        try {
                          await (window as any).api.completePlanItem(props.activeWorkspaceId, it.plan_id, it.id);
                          const data = await (window as any).api.getStudyProgress(props.activeWorkspaceId);
                          setProgress(data);
                        } catch (err) {
                          alert(String(err));
                        }
                      }}>Mark done</button>
                    </div>
                  </li>
                ))}
              </ul>
            </div>

            <h4 style={{ marginTop: 12 }}>Topic mastery</h4>
            <div>
              {Array.isArray(progress.topic_mastery) && progress.topic_mastery.map((t: any) => (
                <div key={t.id} style={{ marginBottom: 10, padding: 8, border: "1px solid #e5e7eb", borderRadius: 6 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12 }}>
                    <div style={{ fontWeight: 600, cursor: "pointer" }} onClick={() => setSelectedTopic(t)}>{t.topic}</div>
                    <div style={{ width: 220 }}>
                      <MasteryBar value={t.mastery_score ?? 0} />
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Topic drilldown modal */}
          {selectedTopic && (
            <div style={{ gridColumn: "1 / -1", marginTop: 16, padding: 12, border: "1px solid #e5e7eb", borderRadius: 8, background: "#fff" }}>
              <button style={{ float: "right" }} onClick={() => setSelectedTopic(null)}>Close</button>
              <h4>{selectedTopic.topic}</h4>
              <div style={{ display: "flex", gap: 16 }}>
                <div style={{ flex: 1 }}>
                  <div><strong>Mastery:</strong> {(selectedTopic.mastery_score * 100).toFixed(0)}%</div>
                  <div><strong>Quiz avg:</strong> {(selectedTopic.quiz_average * 100).toFixed(0)}%</div>
                  <div><strong>Reviews:</strong> {selectedTopic.review_count}</div>
                  <div><strong>Completion:</strong> {(selectedTopic.completion_percentage * 100).toFixed(0)}%</div>
                </div>
                <div style={{ width: 300 }}>
                  <h5>Related upcoming tasks</h5>
                  <ul>
                    {(progress.upcoming_reviews || []).filter((it: any) => it.topic_id === selectedTopic.id).map((it: any) => (
                      <li key={it.id}>{it.task_type} — {it.date}</li>
                    ))}
                    {(progress.todays_tasks || []).filter((it: any) => it.topic_id === selectedTopic.id).map((it: any) => (
                      <li key={it.id}>{it.task_type} — {it.date}</li>
                    ))}
                  </ul>
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
