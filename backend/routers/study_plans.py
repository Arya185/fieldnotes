from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List

from backend.indexer.workspace_manager import workspace_manager
from backend.db import connect_sqlite
from backend.services.planner import generate_study_plan, extract_topics_for_workspace
from backend.storage import ensure_study_tables, list_study_plans, load_study_plan_items
from backend.db import connect_sqlite
from backend.storage import mark_study_plan_item_completed, get_topic, set_topic_progress
from datetime import datetime
from fastapi import Depends
from backend.auth.dependencies import get_current_user
from backend.auth.models import AuthenticatedUser
from backend.auth.security import assert_workspace_access


router = APIRouter()


class CreatePlanRequest(BaseModel):
    workspace_id: str
    title: str
    exam_date: str
    hours_per_day: float = 1.0
    pace: str = "medium"


@router.get("/study-plans")
def get_plans():
    # List plans for default registry DB (global)
    conn = connect_sqlite(workspace_manager._registry_db_path) if hasattr(workspace_manager, "_registry_db_path") else connect_sqlite(":memory:")
    try:
        ensure_study_tables(conn)
        return list_study_plans(conn)
    finally:
        conn.close()


@router.post("/study-plans")
def create_plan(payload: CreatePlanRequest):
    workspace = workspace_manager.get(payload.workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Unknown workspace_id")
    plan_id = generate_study_plan(workspace.db_path, payload.title, payload.exam_date, payload.hours_per_day, payload.pace)
    return {"plan_id": plan_id}


@router.get("/study-plans/{plan_id}")
def get_plan(plan_id: str):
    # naive: search in registry DB
    conn = connect_sqlite(workspace_manager._registry_db_path) if hasattr(workspace_manager, "_registry_db_path") else connect_sqlite(":memory:")
    try:
        ensure_study_tables(conn)
        items = load_study_plan_items(conn, plan_id)
        if not items:
            raise HTTPException(status_code=404, detail="Unknown plan_id")
        return {"plan_id": plan_id, "items": items}
    finally:
        conn.close()


@router.patch("/study-plans/{plan_id}/items/{item_id}/complete")
def complete_plan_item(plan_id: str, item_id: str, workspace_id: str, score: float | None = None, current_user: AuthenticatedUser = Depends(get_current_user)):
    workspace = workspace_manager.get(workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Unknown workspace_id")
    assert_workspace_access(workspace_id, current_user, workspace_manager._repository, ["owner", "teacher", "student", "viewer"])

    conn = connect_sqlite(workspace.db_path)
    try:
        ensure_study_tables(conn)
        row = conn.execute("SELECT * FROM study_plan_items WHERE id = ? AND plan_id = ?", (item_id, plan_id)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Unknown item_id")
        if int(row["completed"]) == 1:
            # already completed, return topic progress
            topic = None
            if row.get("topic_id"):
                topic = get_topic(conn, row["topic_id"])
            return {"status": "ok", "already_completed": True, "topic": topic}

        # mark completed
        mark_study_plan_item_completed(conn, item_id)

        # update topic progress
        topic_id = row.get("topic_id")
        task_type = row.get("task_type")
        if topic_id:
            topic_row = get_topic(conn, topic_id) or {}
            existing_avg = float(topic_row.get("quiz_average") or 0.0)
            existing_reviews = int(topic_row.get("review_count") or 0)

            # update quiz average if score provided (score expected 0..1)
            new_quiz_avg = existing_avg
            if score is not None:
                alpha = 0.4
                new_quiz_avg = (existing_avg * (1 - alpha)) + (score * alpha) if existing_avg > 0 else score

            new_review_count = existing_reviews + (1 if task_type in ("review", "quiz") else 0)
            last_review_iso = datetime.utcnow().isoformat()

            rows_topic_items = conn.execute(
                "SELECT COUNT(*) AS total, SUM(completed) AS done FROM study_plan_items WHERE topic_id = ?",
                (topic_id,),
            ).fetchone()
            total = int(rows_topic_items["total"] or 0)
            done = int(rows_topic_items["done"] or 0)
            completion_pct = (done / total) if total > 0 else 0.0

            review_score = min(1.0, new_review_count / 5.0)
            mastery = 0.6 * float(new_quiz_avg) + 0.2 * float(review_score) + 0.2 * float(completion_pct)
            mastery = max(0.0, min(1.0, mastery))

            set_topic_progress(conn, topic_id, mastery_score=mastery, last_review=last_review_iso, review_count=new_review_count, quiz_average=new_quiz_avg, completion_percentage=completion_pct)
            conn.commit()
            updated = get_topic(conn, topic_id)
            return {"status": "ok", "topic": updated}

        conn.commit()
        return {"status": "ok", "topic": None}
    finally:
        conn.close()
