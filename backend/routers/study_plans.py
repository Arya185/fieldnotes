from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from backend.auth.dependencies import get_current_user
from backend.auth.models import AuthenticatedUser
from backend.auth.security import assert_workspace_access, enforce_rate_limit, get_workspace_repository
from backend.db import connect_sqlite
from backend.indexer.workspace_manager import workspace_manager
from backend.indexer.workspace_repository import WorkspaceRepository
from backend.services.planner import generate_study_plan
from backend.storage import (
    ensure_study_tables,
    get_topic,
    list_study_plans,
    load_study_plan_items,
    mark_study_plan_item_completed,
    set_topic_progress,
)

router = APIRouter()

WORKSPACE_ROLES = ["owner", "teacher", "student", "viewer"]


class CreatePlanRequest(BaseModel):
    workspace_id: str
    title: str
    exam_date: str
    hours_per_day: float = 1.0
    pace: str = "medium"


def _authorized_workspace(
    workspace_id: str,
    current_user: AuthenticatedUser,
    repository: WorkspaceRepository,
):
    workspace = workspace_manager.get(workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Unknown workspace_id")
    assert_workspace_access(
        workspace_id,
        current_user,
        repository,
        WORKSPACE_ROLES,
    )
    return workspace


@router.get("/study-plans")
def get_plans(
    workspace_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repository: WorkspaceRepository = Depends(get_workspace_repository),
):
    workspace = _authorized_workspace(workspace_id, current_user, repository)
    conn = connect_sqlite(workspace.db_path)
    try:
        ensure_study_tables(conn)
        return list_study_plans(conn)
    finally:
        conn.close()


@router.post("/study-plans")
def create_plan(
    payload: CreatePlanRequest,
    request: Request,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repository: WorkspaceRepository = Depends(get_workspace_repository),
):
    workspace = _authorized_workspace(payload.workspace_id, current_user, repository)
    enforce_rate_limit(
        request,
        scope="study_plan_create",
        current_user=current_user,
        capacity=6,
        refill_period_seconds=60,
    )
    plan_id = generate_study_plan(
        workspace.db_path,
        payload.title,
        payload.exam_date,
        payload.hours_per_day,
        payload.pace,
    )
    return {"plan_id": plan_id}


@router.get("/study-plans/{plan_id}")
def get_plan(
    plan_id: str,
    workspace_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repository: WorkspaceRepository = Depends(get_workspace_repository),
):
    workspace = _authorized_workspace(workspace_id, current_user, repository)
    conn = connect_sqlite(workspace.db_path)
    try:
        ensure_study_tables(conn)
        plans = {plan["id"]: plan for plan in list_study_plans(conn)}
        if plan_id not in plans:
            raise HTTPException(status_code=404, detail="Unknown plan_id")
        items = load_study_plan_items(conn, plan_id)
        return {"plan_id": plan_id, "plan": plans[plan_id], "items": items}
    finally:
        conn.close()


@router.patch("/study-plans/{plan_id}/items/{item_id}/complete")
def complete_plan_item(
    plan_id: str,
    item_id: str,
    workspace_id: str,
    score: float | None = None,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repository: WorkspaceRepository = Depends(get_workspace_repository),
):
    workspace = _authorized_workspace(workspace_id, current_user, repository)

    conn = connect_sqlite(workspace.db_path)
    try:
        ensure_study_tables(conn)
        row = conn.execute(
            "SELECT * FROM study_plan_items WHERE id = ? AND plan_id = ?",
            (item_id, plan_id),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Unknown item_id")
        if int(row["completed"]) == 1:
            topic = None
            if row["topic_id"]:
                topic = get_topic(conn, row["topic_id"])
            return {"status": "ok", "already_completed": True, "topic": topic}

        mark_study_plan_item_completed(conn, item_id)

        topic_id = row["topic_id"]
        task_type = row["task_type"]
        if topic_id:
            topic_row = get_topic(conn, topic_id) or {}
            existing_avg = float(topic_row.get("quiz_average") or 0.0)
            existing_reviews = int(topic_row.get("review_count") or 0)

            new_quiz_avg = existing_avg
            if score is not None:
                alpha = 0.4
                new_quiz_avg = (
                    (existing_avg * (1 - alpha)) + (score * alpha)
                    if existing_avg > 0
                    else score
                )

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

            set_topic_progress(
                conn,
                topic_id,
                mastery_score=mastery,
                last_review=last_review_iso,
                review_count=new_review_count,
                quiz_average=new_quiz_avg,
                completion_percentage=completion_pct,
            )
            conn.commit()
            updated = get_topic(conn, topic_id)
            return {"status": "ok", "topic": updated}

        conn.commit()
        return {"status": "ok", "topic": None}
    finally:
        conn.close()
