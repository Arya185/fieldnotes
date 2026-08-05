from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List
from uuid import uuid4

from backend.db import connect_sqlite
from backend.storage import ensure_study_tables, upsert_topic, insert_study_plan, insert_study_plan_item, list_topics
from backend.agent.llm import LLMClient


@dataclass
class TopicMeta:
    id: str
    topic: str
    summary: str | None
    difficulty: str | None
    est_minutes: int | None
    prerequisites: List[str]


def extract_topics_for_workspace(db_path: str) -> List[TopicMeta]:
    """Extract topics for a workspace using the LLM when available.

    Produces a list of `TopicMeta` and persists each topic via `upsert_topic`.
    If the LLM call fails, falls back to the previous heuristic behavior.
    """
    connection = connect_sqlite(db_path)
    try:
        ensure_study_tables(connection)
        # If topics already exist, return them
        rows = list_topics(connection)
        if rows:
            return [
                TopicMeta(
                    id=row["id"],
                    topic=row["topic"],
                    summary=row.get("summary"),
                    difficulty=row.get("difficulty"),
                    est_minutes=row.get("est_minutes"),
                    prerequisites=json.loads(row.get("prerequisites_json")) if row.get("prerequisites_json") else [],
                )
                for row in rows
            ]

        # Build a lightweight file list to give the LLM context
        file_rows = connection.execute("SELECT id, path FROM files ORDER BY path").fetchall()
        files = [{"id": r["id"], "path": r["path"]} for r in file_rows]

        # Try LLM extraction
        try:
            llm = LLMClient()
            schema = {
                "type": "object",
                "properties": {
                    "topics": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "topic": {"type": "string"},
                                "summary": {"type": ["string", "null"]},
                                "difficulty": {"type": ["string", "null"]},
                                "est_minutes": {"type": ["integer", "null"]},
                                "prerequisites": {"type": "array", "items": {"type": "string"}},
                                "file_id": {"type": ["string", "null"]},
                            },
                            "required": ["topic"],
                            "additionalProperties": False,
                        },
                    }
                },
                "required": ["topics"],
                "additionalProperties": False,
            }

            input_items = [
                {
                    "role": "developer",
                    "content": (
                        "Extract a concise list of studyable topics from the workspace files. "
                        "For each topic return: topic, optional summary, difficulty (easy|moderate|hard) or null, "
                        "estimated minutes for a first pass (integer) or null, prerequisites as an array of topic names, and optionally the file_id when the topic is primarily from one file. "
                        "Return strict JSON only following the schema."
                    ),
                },
                {"role": "user", "content": f"Files:\n{json.dumps(files, ensure_ascii=False)}"},
            ]

            response = llm._create_structured_completion(
                response_name="topic_extraction",
                schema=schema,
                input_items=input_items,
                max_output_tokens=1200,
            )
            output_text = llm._response_output_text(response)
            parsed = json.loads(output_text)
            topics: List[TopicMeta] = []
            for item in parsed.get("topics", []):
                tid = f"topic_{uuid4().hex[:8]}"
                topic_name = item.get("topic")
                summary = item.get("summary")
                difficulty = item.get("difficulty")
                est_minutes = item.get("est_minutes")
                prerequisites = item.get("prerequisites") or []
                file_id = item.get("file_id")
                topics.append(TopicMeta(id=tid, topic=topic_name, summary=summary, difficulty=difficulty, est_minutes=est_minutes, prerequisites=prerequisites))
                upsert_topic(connection, tid, topic_name, summary, difficulty, est_minutes, json.dumps(prerequisites), file_id)

            connection.commit()
            if topics:
                return topics
        except Exception:
            # LLM failure should not block functionality; fall through to heuristics
            pass

        # Fallback heuristic: derive naive topics from files table
        topics: List[TopicMeta] = []
        for row in file_rows:
            tid = f"topic_{uuid4().hex[:8]}"
            topics.append(TopicMeta(id=tid, topic=row["path"], summary=None, difficulty=None, est_minutes=None, prerequisites=[]))
            upsert_topic(connection, tid, row["path"], None, None, None, json.dumps([]), row["id"])
        connection.commit()
        return topics
    finally:
        connection.close()


def generate_study_plan(db_path: str, title: str, exam_date: str, hours_per_day: float, pace: str) -> str:
    connection = connect_sqlite(db_path)
    try:
        ensure_study_tables(connection)
        topics = extract_topics_for_workspace(db_path)
        plan_id = f"plan_{uuid4().hex[:8]}"
        insert_study_plan(connection, plan_id, title, exam_date, hours_per_day, pace)

        # Improved scheduling:
        # - respect prerequisites (topological order)
        # - weight topics by estimated minutes or difficulty
        # - allocate total available minutes across days
        # - schedule initial read + spaced review/quiz items
        start = datetime.utcnow().date()
        end = datetime.fromisoformat(exam_date).date()
        total_days = max((end - start).days, 1)

        # Build lookup for prerequisites by resolving names to topic ids
        name_to_id = {t.topic: t.id for t in topics}
        prereq_map: dict[str, list[str]] = {}
        for t in topics:
            resolved = [name_to_id.get(name) for name in t.prerequisites or [] if name_to_id.get(name)]
            prereq_map[t.id] = [r for r in resolved if r]

        # Topological sort (Kahn's algorithm) to respect prerequisites order
        in_degree = {t.id: 0 for t in topics}
        for deps in prereq_map.values():
            for d in deps:
                in_degree[d] = in_degree.get(d, 0) + 0  # ensure key
        for tid, deps in prereq_map.items():
            for dep in deps:
                in_degree[tid] = in_degree.get(tid, 0) + 1

        queue = [tid for tid, deg in in_degree.items() if deg == 0]
        topo: list[str] = []
        adj = {t.id: [] for t in topics}
        for tid, deps in prereq_map.items():
            for dep in deps:
                adj[dep].append(tid)

        while queue:
            cur = queue.pop(0)
            topo.append(cur)
            for neigh in adj.get(cur, []):
                in_degree[neigh] -= 1
                if in_degree[neigh] == 0:
                    queue.append(neigh)

        if not topo:
            topo = [t.id for t in topics]

        # Compute total available minutes
        total_minutes = int(total_days * max(0.0, hours_per_day) * 60)
        if total_minutes <= 0:
            total_minutes = max(60, len(topics) * 30)

        # Compute base weights per topic
        default_est = 30
        difficulty_factor = {"easy": 0.8, "moderate": 1.0, "hard": 1.3}
        weights: dict[str, float] = {}
        total_weight = 0.0
        for t in topics:
            base = (t.est_minutes or default_est)
            factor = difficulty_factor.get((t.difficulty or "").lower(), 1.0)
            w = max(5.0, base * factor)
            weights[t.id] = w
            total_weight += w

        # Scale weights to minutes allocation
        minutes_alloc: dict[str, int] = {}
        for tid, w in weights.items():
            minutes_alloc[tid] = max(10, int(round(w / total_weight * total_minutes)))

        # Prepare per-day remaining minutes
        days = [start + timedelta(days=i) for i in range(total_days)]
        day_remaining = {d.isoformat(): int(max(0, hours_per_day * 60)) for d in days}
        # If hours_per_day is zero, set a small default daily budget
        if all(v == 0 for v in day_remaining.values()):
            for k in day_remaining:
                day_remaining[k] = 60

        # Helper to find earliest day with capacity
        def find_day_for(duration: int, earliest_index: int = 0) -> int:
            for i in range(earliest_index, len(days)):
                if day_remaining[days[i].isoformat()] >= duration:
                    return i
            # fallback: place on last day
            return len(days) - 1

        # Schedule items following topo order
        schedule_index = 0
        for tid in topo:
            topic_meta = next((x for x in topics if x.id == tid), None)
            if topic_meta is None:
                continue
            remaining = minutes_alloc.get(tid, default_est)
            # schedule main 'read' item (may split across days if large)
            while remaining > 0:
                idx = find_day_for(min(remaining, 120), schedule_index)
                day_iso = days[idx].isoformat()
                alloc = min(remaining, day_remaining[day_iso], 120)
                if alloc <= 0:
                    # advance to next day
                    schedule_index = idx + 1
                    if schedule_index >= len(days):
                        schedule_index = len(days) - 1
                    # force a small allocation
                    alloc = min(remaining, 30)
                item_id = f"item_{uuid4().hex[:8]}"
                insert_study_plan_item(connection, item_id, plan_id, tid, day_iso, "read", int(alloc))
                day_remaining[day_iso] = max(0, day_remaining[day_iso] - int(alloc))
                remaining -= int(alloc)

            # schedule spaced review items: quick review next day, quiz 3 days later, follow-up 7 days later
            try:
                idx_main = find_day_for(1, 0)
                review_dates = []
                if len(days) >= 2:
                    review_dates.append(days[min(len(days) - 1, idx_main + 1)].isoformat())
                if len(days) >= 4:
                    review_dates.append(days[min(len(days) - 1, idx_main + 3)].isoformat())
                if len(days) >= 8:
                    review_dates.append(days[min(len(days) - 1, idx_main + 7)].isoformat())
                for rd in review_dates:
                    # small review/quiz durations
                    if rd == review_dates[1] if len(review_dates) > 1 else False:
                        task = "quiz"
                        dur = 10
                    else:
                        task = "review"
                        dur = 15
                    item_id = f"item_{uuid4().hex[:8]}"
                    insert_study_plan_item(connection, item_id, plan_id, tid, rd, task, dur)
                    # best-effort reduce day_remaining
                    if rd in day_remaining:
                        day_remaining[rd] = max(0, day_remaining[rd] - dur)
            except Exception:
                # do not fail plan generation on scheduling edge cases
                pass

        connection.commit()
        return plan_id
    finally:
        connection.close()


def adjust_plan_on_quiz_result(db_path: str, topic_id: str | None, is_correct: bool, score: float | None = None) -> None:
    connection = connect_sqlite(db_path)
    try:
        ensure_study_tables(connection)
        # find plans referencing this topic
        rows = connection.execute(
            "SELECT id FROM study_plans"
        ).fetchall()
        plan_ids = [r["id"] for r in rows]
        from backend.storage import load_study_plan_items, mark_study_plan_item_completed, add_review_item

        for pid in plan_ids:
            items = load_study_plan_items(connection, pid)
            # find next upcoming item for this topic
            upcoming = [it for it in items if it.get("topic_id") == topic_id and not it.get("completed")]
            if is_correct:
                # reduce repetitions: mark one future item as completed
                if upcoming:
                    mark_study_plan_item_completed(connection, upcoming[0]["id"])
            else:
                # schedule additional review tomorrow
                tomorrow = (datetime.utcnow().date() + timedelta(days=1)).isoformat()
                add_review_item(connection, pid, topic_id, tomorrow, 30)
        # Update topic progress / mastery
        if topic_id is not None:
            from backend.storage import get_topic, set_topic_progress

            topic_row = get_topic(connection, topic_id)
            existing_avg = float(topic_row.get("quiz_average") or 0.0) if topic_row else 0.0
            existing_reviews = int(topic_row.get("review_count") or 0) if topic_row else 0

            # update review count and last review
            new_review_count = existing_reviews + 1
            last_review_iso = datetime.utcnow().isoformat()

            # update quiz average via simple EMA if score provided
            new_quiz_avg = existing_avg
            if score is not None:
                alpha = 0.4
                new_quiz_avg = (existing_avg * (1 - alpha)) + (score * alpha) if existing_avg > 0 else score

            # compute completion percentage for this topic across all plan items
            rows_topic_items = connection.execute(
                "SELECT COUNT(*) AS total, SUM(completed) AS done FROM study_plan_items WHERE topic_id = ?",
                (topic_id,),
            ).fetchone()
            total = int(rows_topic_items["total"] or 0)
            done = int(rows_topic_items["done"] or 0)
            completion_pct = (done / total) if total > 0 else 0.0

            # compute mastery: weighted sum of quiz avg, review coverage, completion
            review_score = min(1.0, new_review_count / 5.0)
            mastery = 0.6 * float(new_quiz_avg) + 0.2 * float(review_score) + 0.2 * float(completion_pct)

            # recency decay: if last review > 14 days, reduce mastery gradually
            days_since = 0
            try:
                days_since = (datetime.utcnow() - datetime.fromisoformat(last_review_iso)).days
            except Exception:
                days_since = 0
            if days_since > 14:
                decay = max(0.6, 1.0 - (days_since - 14) / 30.0)
                mastery = mastery * decay

            # clamp between 0 and 1
            mastery = max(0.0, min(1.0, mastery))

            set_topic_progress(
                connection,
                topic_id,
                mastery_score=mastery,
                last_review=last_review_iso,
                review_count=new_review_count,
                quiz_average=new_quiz_avg,
                completion_percentage=completion_pct,
            )
        connection.commit()
    finally:
        connection.close()
