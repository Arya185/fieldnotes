from __future__ import annotations

import json
import sqlite3
from collections.abc import AsyncIterator, Callable
from uuid import uuid4

from fastapi import Request

from backend.db import connect_sqlite
from backend.errors import request_id_for, sse_error_payload
from backend.indexer.workspace_manager import workspace_manager
from backend.indexer.vectors import get_retrieval_provider
from backend.models import (
    CitationChip,
    ConceptUpdate,
    GradedEvent,
    QuestionEvent,
    QuizAnswerRequest,
    QuizDoneEvent,
    QuizRequest,
)
from backend.storage import (
    create_artifact,
    create_quiz_attempt,
    get_concept_id_by_name,
    load_chunk_by_anchor,
    load_file_path_by_id,
    load_most_recently_answered_concept,
    load_quiz_attempt,
    load_recent_quiz_attempts_for_concept,
    record_quiz_answer,
    upsert_concept_updates,
    validate_citation_anchors,
)

from .retrieval import load_fallback_retrieval
from .starters import build_refreshed_starters
from backend.services.planner import adjust_plan_on_quiz_result


def load_quiz_concept_names(
    connection: sqlite3.Connection, exclude_recent: str | None = None
) -> list[str]:
    """Pick candidate concepts for the next question, shakiest first.

    `exclude_recent` is the name of the concept behind the just-answered
    question. Rather than dropping it, it is pushed to the back of the
    candidate list so a missed concept still comes back for review, just not
    as the very next question — avoiding immediate drilling.
    """

    rows = connection.execute(
        """
        SELECT name
        FROM concepts
        ORDER BY CASE state WHEN 'shaky' THEN 0 ELSE 1 END, updated_at DESC
        LIMIT 5
        """
    ).fetchall()
    names = [str(row["name"]) for row in rows]
    if exclude_recent and exclude_recent in names and len(names) > 1:
        names.remove(exclude_recent)
        names.append(exclude_recent)
    return names


def compute_quiz_difficulty(connection: sqlite3.Connection, concept_id: str | None) -> str:
    """Scale next-question difficulty from rolling accuracy on one concept this session.

    Two-in-a-row correct raises difficulty to "hard" (cross-passage synthesis).
    A miss on the most recent attempt drops it to "easy" (single-fact recall)
    so a requeued concept is gentler the next time it comes up. No history
    (first time this concept is quizzed) stays "medium".
    """

    if not concept_id:
        return "medium"
    recent = load_recent_quiz_attempts_for_concept(connection, concept_id, limit=5)
    if not recent:
        return "medium"
    if not bool(recent[0]["is_correct"]):
        return "easy"
    streak = 0
    for attempt in recent:
        if bool(attempt["is_correct"]):
            streak += 1
        else:
            break
    return "hard" if streak >= 2 else "medium"


async def stream_quiz_start_events(
    request: QuizRequest,
    http_request: Request,
    get_llm_client: Callable[[], object],
    sse: Callable[[dict], str],
) -> AsyncIterator[str]:
    request_id = request_id_for(http_request)
    try:
        workspace_record = workspace_manager.get(request.workspace_id)
        if workspace_record is None:
            raise ValueError(f"Unknown workspace_id: {request.workspace_id}")
        client = get_llm_client()

        connection = connect_sqlite(workspace_record.db_path)
        try:
            retrieval_provider = get_retrieval_provider(connection)
            if request.concept_ids:
                concept_ids = request.concept_ids
            else:
                previous = load_most_recently_answered_concept(connection)
                concept_ids = load_quiz_concept_names(
                    connection, exclude_recent=previous["name"] if previous else None
                )
            concept_query = " ".join(concept_ids) or "important concepts"
            retrieval_results = retrieval_provider.search(concept_query, limit=5)
            if not retrieval_results:
                retrieval_results = load_fallback_retrieval(connection, limit=5)
            if not retrieval_results:
                raise ValueError(
                    "No indexed content available for quiz generation. Re-check the folder path and supported file types (pdf, pptx, docx, md, txt, csv)."
                )

            target_concept_id = get_concept_id_by_name(connection, concept_ids[0]) if concept_ids else None
            difficulty = compute_quiz_difficulty(connection, target_concept_id)

            question = client.generate_quiz_question(
                retrieval_results,
                concept_ids,
                difficulty=difficulty,
            )
            if "#" not in question.source_anchor:
                raise ValueError("Quiz source_anchor is not a full anchor")
            file_id, locator = question.source_anchor.split("#", 1)
            if load_chunk_by_anchor(connection, file_id, locator) is None:
                raise ValueError(
                    f"Quiz source_anchor does not resolve to a persisted chunk: {question.source_anchor}"
                )
            file_path = load_file_path_by_id(connection, file_id)
            if file_path is None:
                raise ValueError(f"Unknown file for quiz source_anchor: {question.source_anchor}")
            concept_update = client.extract_concepts(
                question.question,
                retrieval_results,
            )
            upsert_concept_updates(connection, concept_update, source_anchor=question.source_anchor)
            concept_id = concept_update[0].concept_id if concept_update else "concept_quiz"
            attempt_id = create_quiz_attempt(
                connection,
                concept_id=concept_id,
                question=question.question,
                options=question.options,
                correct_index=question.correct_index,
                source_anchor=question.source_anchor,
            )
            connection.commit()
        finally:
            connection.close()

        yield sse(
            QuestionEvent(
                event="question",
                attempt_id=attempt_id,
                index=1,
                total=1,
                question=question.question,
                options=question.options,
                source_label=f"{file_path} {locator}",
                source_anchor=question.source_anchor,
                difficulty=difficulty,
            ).model_dump()
        )
    except Exception as exc:
        yield sse(
            sse_error_payload(
                exc=exc,
                request_id=request_id,
                answer_id=f"quiz_{uuid4()}",
                context={"route": "/quiz/start", "workspace_id": request.workspace_id},
            )
        )


async def stream_quiz_answer_events(
    request: QuizAnswerRequest,
    http_request: Request,
    sse: Callable[[dict], str],
) -> AsyncIterator[str]:
    request_id = request_id_for(http_request)
    try:
        workspace_record = workspace_manager.get(request.workspace_id)
        if workspace_record is None:
            raise ValueError(f"Unknown workspace_id: {request.workspace_id}")

        connection = connect_sqlite(workspace_record.db_path)
        try:
            attempt = load_quiz_attempt(connection, request.attempt_id)
            if attempt is None:
                raise ValueError(f"Unknown attempt_id: {request.attempt_id}")
            updated_attempt = record_quiz_answer(connection, request.attempt_id, request.chosen_index)
            if updated_attempt is None:
                raise ValueError(f"Unable to persist quiz answer: {request.attempt_id}")

            concept_update = ConceptUpdate(
                concept_id=str(updated_attempt["concept_id"]),
                name=str(updated_attempt["concept_name"]),
                state="touched" if int(updated_attempt["is_correct"]) else "shaky",
            )
            upsert_concept_updates(
                connection,
                [concept_update],
                source_anchor=str(updated_attempt["source_anchor"]),
                answer_id=request.attempt_id,
            )
            file_id, locator = str(updated_attempt["source_anchor"]).split("#", 1)
            chip = CitationChip(
                chip_type="document",
                label=f"{load_file_path_by_id(connection, file_id) or file_id} {locator}",
                anchor=str(updated_attempt["source_anchor"]),
            )
            valid_chip_list = validate_citation_anchors(connection, [chip])
            if not valid_chip_list:
                raise ValueError(
                    f"Quiz citation does not resolve to a persisted chunk: {updated_attempt['source_anchor']}"
                )
            result_payload = json.dumps(
                {
                    "attempt_id": request.attempt_id,
                    "is_correct": bool(int(updated_attempt["is_correct"])),
                    "chosen_index": request.chosen_index,
                    "correct_index": int(updated_attempt["correct_index"]),
                }
            )
            artifact_card = create_artifact(
                connection,
                workspace_record.artifacts_dir,
                kind="quiz_result",
                title=f"Quiz result: {updated_attempt['concept_name']}",
                answer_id=request.attempt_id,
                payload_text=result_payload,
            )
            refreshed_starters = build_refreshed_starters(connection)
            connection.commit()
        finally:
            connection.close()

        is_correct = bool(int(updated_attempt["is_correct"]))
        explanation = (
            "Correct. The answer matches the grounded source passage."
            if is_correct
            else "Not correct. Review the cited source passage for the grounded explanation."
        )
        concept_state = "touched" if is_correct else "shaky"

        yield sse(
            GradedEvent(
                event="graded",
                attempt_id=request.attempt_id,
                is_correct=is_correct,
                correct_index=int(updated_attempt["correct_index"]),
                explanation=explanation,
                chip=valid_chip_list[0],
                concept_update=ConceptUpdate(
                    concept_id=str(updated_attempt["concept_id"]),
                    name=str(updated_attempt["concept_name"]),
                    state=concept_state,
                ),
            ).model_dump()
        )
        yield sse(
            QuizDoneEvent(
                event="quiz_done",
                score=1 if is_correct else 0,
                total=1,
                artifact_id=artifact_card.id,
                refreshed_starters=refreshed_starters,
            ).model_dump()
        )
        # Adaptive study plan adjustments
        try:
            concept_topic_id = str(updated_attempt["concept_id"]) if updated_attempt.get("concept_id") else None
            adjust_plan_on_quiz_result(workspace_record.db_path, concept_topic_id, is_correct, 1.0 if is_correct else 0.0)
        except Exception:
            # Do not fail quiz flow due to planner errors
            pass
    except Exception as exc:
        yield sse(
            sse_error_payload(
                exc=exc,
                request_id=request_id,
                answer_id=f"quiz_{uuid4()}",
                context={"route": "/quiz/answer", "workspace_id": request.workspace_id, "attempt_id": request.attempt_id},
            )
        )
