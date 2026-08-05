from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from backend.auth.dependencies import get_current_user
from backend.auth.models import AuthenticatedUser
from backend.auth.security import assert_workspace_access
from backend.indexer.workspace_manager import workspace_manager
from backend.models import (
    FlashcardListResponse,
    FlashcardReviewRequest,
    FlashcardReviewResponse,
    GenerateFlashcardsRequest,
)
from backend.services.flashcards import (
    generate_flashcards_for_workspace,
    list_flashcards_for_workspace,
    review_flashcard,
)

router = APIRouter()

WORKSPACE_ROLES = ["owner", "teacher", "student", "viewer"]


@router.post("/flashcards/generate")
def post_generate_flashcards(
    payload: GenerateFlashcardsRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> FlashcardListResponse:
    """Generate a grounded batch of flashcards for one workspace or topic."""

    workspace = workspace_manager.get(payload.workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Unknown workspace_id")
    assert_workspace_access(
        payload.workspace_id, current_user, workspace_manager._repository, WORKSPACE_ROLES
    )

    try:
        cards = generate_flashcards_for_workspace(
            workspace.db_path,
            topic_id=payload.topic_id,
            count=payload.count,
            card_types=payload.card_types,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return FlashcardListResponse(flashcards=cards)


@router.get("/flashcards")
def get_flashcards(
    workspace_id: str,
    topic_id: str | None = None,
    due_only: bool = False,
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> FlashcardListResponse:
    """List persisted flashcards for one workspace, optionally filtered by topic or due date."""

    workspace = workspace_manager.get(workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Unknown workspace_id")
    assert_workspace_access(
        workspace_id, current_user, workspace_manager._repository, WORKSPACE_ROLES
    )

    cards = list_flashcards_for_workspace(workspace.db_path, topic_id=topic_id, due_only=due_only)
    return FlashcardListResponse(flashcards=cards)


@router.post("/flashcards/review")
def post_review_flashcard(
    payload: FlashcardReviewRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> FlashcardReviewResponse:
    """Grade one flashcard review, applying SM-2 spaced repetition and planner reactions."""

    workspace = workspace_manager.get(payload.workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Unknown workspace_id")
    assert_workspace_access(
        payload.workspace_id, current_user, workspace_manager._repository, WORKSPACE_ROLES
    )

    try:
        flashcard, topic_mastery, generated_more = review_flashcard(
            workspace.db_path, payload.flashcard_id, payload.confidence
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FlashcardReviewResponse(
        flashcard=flashcard, topic_mastery=topic_mastery, generated_more=generated_more
    )
