import React, { useEffect, useState } from "react";
import { getStudyPlans, createStudyPlan } from "../lib/api";

export function StudyPlannerRoute(props: { activeWorkspaceId?: string | null }) {
  const [plans, setPlans] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    async function load() {
      setLoading(true);
      try {
        const data = await getStudyPlans();
        setPlans(Array.isArray(data) ? data : []);
      } finally {
        setLoading(false);
      }
    }
    void load();
  }, []);

  async function handleCreate() {
    if (!props.activeWorkspaceId) return;
    try {
      const payload = { workspace_id: props.activeWorkspaceId, title: "Auto Plan", exam_date: new Date(Date.now() + 7 * 24 * 3600 * 1000).toISOString().slice(0, 10), hours_per_day: 1.0, pace: "moderate" };
      const res = await createStudyPlan(payload);
      alert(`Created plan ${res.plan_id}`);
    } catch (err) {
      alert(String(err));
    }
  }

  return (
    <div className="study-planner">
      <h3>Study Planner</h3>
      <button className="button" onClick={handleCreate} disabled={!props.activeWorkspaceId}>Generate Plan</button>
      {loading ? <p>Loading...</p> : (
        <ul>
          {plans.map((p) => (
            <li key={p.id}>{p.title ?? p.id}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
