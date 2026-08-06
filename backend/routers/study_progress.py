from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime, timedelta, date

from backend.indexer.workspace_manager import workspace_manager
from backend.indexer.workspace_repository import WorkspaceRepository
from backend.db import connect_sqlite
from backend.storage import ensure_study_tables, list_topics, load_study_plan_items
from backend.auth.dependencies import get_current_user
from backend.auth.models import AuthenticatedUser
from backend.auth.security import assert_workspace_access, get_workspace_repository

router = APIRouter()


@router.get("/study-progress")
def get_study_progress(
    workspace_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repository: WorkspaceRepository = Depends(get_workspace_repository),
):
    workspace = workspace_manager.get(workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Unknown workspace_id")
    assert_workspace_access(workspace_id, current_user, repository, ["owner", "teacher", "student", "viewer"])

    conn = connect_sqlite(workspace.db_path)
    try:
        ensure_study_tables(conn)
        topics = list_topics(conn)
        items = load_study_plan_items(conn, None) if False else conn.execute("SELECT * FROM study_plan_items ORDER BY date").fetchall()

        # overall completion
        total_items = 0
        completed_items = 0
        for it in items:
            total_items += 1
            if int(it["completed"]) == 1:
                completed_items += 1
        overall_completion = (completed_items / total_items) if total_items > 0 else 0.0

        # topic mastery details
        topic_mastery = []
        weak = []
        for t in topics:
            mastery = float(t.get("mastery_score") or 0.0)
            topic_mastery.append({
                "id": t.get("id"),
                "topic": t.get("topic"),
                "mastery_score": mastery,
                "last_review": t.get("last_review"),
                "review_count": int(t.get("review_count") or 0),
                "quiz_average": float(t.get("quiz_average") or 0.0),
                "completion_percentage": float(t.get("completion_percentage") or 0.0),
            })
            if mastery < 0.6:
                weak.append({"id": t.get("id"), "topic": t.get("topic"), "mastery_score": mastery})

        # today's tasks
        today_iso = date.today().isoformat()
        todays = [
            dict(it) for it in conn.execute("SELECT * FROM study_plan_items WHERE date = ? AND completed = 0 ORDER BY date", (today_iso,)).fetchall()
        ]

        # upcoming reviews (next 7 days)
        upcoming = []
        for i in range(1, 8):
            d = (date.today() + timedelta(days=i)).isoformat()
            rows = conn.execute("SELECT * FROM study_plan_items WHERE date = ? AND task_type IN ('review','quiz') AND completed = 0", (d,)).fetchall()
            for r in rows:
                upcoming.append(dict(r))

        # study streak: count consecutive days with completed items up to today
        streak = 0
        for i in range(0, 30):
            d = (date.today() - timedelta(days=i)).isoformat()
            row = conn.execute("SELECT SUM(completed) AS done FROM study_plan_items WHERE date = ?", (d,)).fetchone()
            if row and int(row["done"] or 0) > 0:
                streak += 1
            else:
                break

        # estimated exam readiness: map overall_completion and average mastery
        avg_mastery = (sum([m["mastery_score"] for m in topic_mastery]) / len(topic_mastery)) if topic_mastery else 0.0
        est_readiness = 0.6 * overall_completion + 0.4 * avg_mastery

        return {
            "overall_completion": overall_completion,
            "avg_mastery": avg_mastery,
            "topic_mastery": topic_mastery,
            "todays_tasks": todays,
            "upcoming_reviews": upcoming,
            "weak_topics": weak,
            "study_streak": streak,
            "estimated_exam_readiness": est_readiness,
        }
    finally:
        conn.close()
