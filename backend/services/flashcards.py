"""Flashcard generation, SM-2 spaced repetition, and planner integration."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from uuid import uuid4

from backend.config import determine_llm_mode
from backend.db import connect_sqlite
from backend.indexer.vectors import get_retrieval_provider
from backend.models import Flashcard
from backend.storage import (
    avg_flashcard_mastery_for_topic,
    count_flashcards_for_topic,
    ensure_study_tables,
    get_flashcard,
    get_topic,
    insert_flashcard,
    list_flashcards,
    load_chunk_by_anchor,
    load_file_path_by_id,
    set_topic_progress,
    update_flashcard_review,
    utc_now_iso,
)
from .retrieval import load_fallback_retrieval

ALL_CARD_TYPES: list[str] = [
    "definition",
    "concept",
    "application",
    "true_false",
    "fill_blank",
    "scenario",
]

CONFIDENCE_QUALITY: dict[str, int] = {"again": 1, "hard": 3, "good": 4, "easy": 5}

LOW_MASTERY_THRESHOLD = 0.5
HIGH_MASTERY_THRESHOLD = 0.85
DUE_CARD_FLOOR = 8
TOPUP_BATCH_SIZE = 5


def _get_llm_client():
    from backend.agent.llm import LLMClient
    from backend.release import FakeLLMClient

    return FakeLLMClient() if determine_llm_mode() == "fake" else LLMClient()


def sm2_update(
    ease_factor: float, interval_days: float, review_count: int, quality: int
) -> tuple[float, float, int]:
    """Apply one SM-2 style update. Returns (ease_factor, interval_days, review_count)."""

    quality = max(0, min(5, quality))
    new_ease = ease_factor + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    new_ease = max(1.3, new_ease)

    if quality < 3:
        return new_ease, 1.0, 0

    new_review_count = review_count + 1
    if new_review_count == 1:
        new_interval = 1.0
    elif new_review_count == 2:
        new_interval = 6.0
    else:
        base_interval = interval_days if interval_days > 0 else 6.0
        new_interval = round(base_interval * new_ease, 2)
    return new_ease, new_interval, new_review_count


def _next_mastery_weight(current: float, quality: int) -> float:
    if quality < 3:
        delta = -0.25
    elif quality == 3:
        delta = 0.1
    elif quality == 4:
        delta = 0.16
    else:
        delta = 0.22
    return max(0.0, min(1.0, current + delta))


def _row_to_flashcard(row: dict) -> Flashcard:
    return Flashcard(
        id=str(row["id"]),
        topic_id=row["topic_id"],
        card_type=row["card_type"],
        question=row["question"],
        answer=row["answer"],
        difficulty=row["difficulty"],
        bloom_level=row["bloom_level"],
        source_document=row["source_document"],
        source_locator=row["source_locator"],
        review_interval=float(row["review_interval"]),
        ease_factor=float(row["ease_factor"]),
        next_review=row["next_review"],
        last_review=row["last_review"],
        review_count=int(row["review_count"]),
        mastery_weight=float(row["mastery_weight"]),
    )


def generate_flashcards_for_workspace(
    db_path,
    *,
    topic_id: str | None = None,
    count: int = 10,
    card_types: list[str] | None = None,
    llm_client=None,
) -> list[Flashcard]:
    """Generate and persist a grounded batch of flashcards for one workspace."""

    connection = connect_sqlite(db_path)
    try:
        ensure_study_tables(connection)
        retrieval_provider = get_retrieval_provider(connection)

        topic_hint = None
        if topic_id:
            topic_row = get_topic(connection, topic_id)
            topic_hint = topic_row.get("topic") if topic_row else None

        query = topic_hint or "important concepts"
        retrieval_results = retrieval_provider.search(query, limit=8)
        if not retrieval_results:
            retrieval_results = load_fallback_retrieval(connection, limit=8)
        if not retrieval_results:
            raise ValueError(
                "No indexed content available for flashcard generation. "
                "Re-check the folder path and supported file types (pdf, pptx, docx, md, txt, csv)."
            )

        client = llm_client or _get_llm_client()
        selected_types = card_types or ALL_CARD_TYPES
        batch = client.generate_flashcards(
            retrieval_results=retrieval_results,
            count=count,
            card_types=selected_types,
            topic_hint=topic_hint,
        )

        valid_anchors = {f"{result.file_id}#{result.anchor}" for result in retrieval_results}
        now_iso = utc_now_iso()
        today_iso = date.today().isoformat()
        created: list[Flashcard] = []
        for item in batch.flashcards:
            if item.source_anchor not in valid_anchors or "#" not in item.source_anchor:
                continue
            file_id, locator = item.source_anchor.split("#", 1)
            chunk_row = load_chunk_by_anchor(connection, file_id, locator)
            if chunk_row is None:
                continue
            file_path = load_file_path_by_id(connection, file_id) or file_id

            record = {
                "id": f"flashcard_{uuid4().hex[:12]}",
                "topic_id": topic_id,
                "card_type": item.card_type,
                "question": item.question,
                "answer": item.answer,
                "difficulty": item.difficulty,
                "bloom_level": item.bloom_level,
                "source_document": file_path,
                "source_locator": locator,
                "source_anchor": item.source_anchor,
                "source_chunk_id": str(chunk_row["id"]),
                "review_interval": 0.0,
                "ease_factor": 2.5,
                "next_review": today_iso,
                "last_review": None,
                "review_count": 0,
                "mastery_weight": 0.0,
                "created_at": now_iso,
            }
            insert_flashcard(connection, record)
            created.append(_row_to_flashcard(record))

        if not created:
            raise ValueError("Flashcard generation produced no citation-verified cards.")

        connection.commit()
    finally:
        connection.close()
    return created


def list_flashcards_for_workspace(
    db_path,
    *,
    topic_id: str | None = None,
    due_only: bool = False,
) -> list[Flashcard]:
    """List persisted flashcards for one workspace."""

    connection = connect_sqlite(db_path)
    try:
        ensure_study_tables(connection)
        rows = list_flashcards(connection, topic_id=topic_id, due_only=due_only)
        return [_row_to_flashcard(row) for row in rows]
    finally:
        connection.close()


def _rebalance_topic_mastery(connection, topic_id: str) -> float | None:
    """Blend flashcard mastery into topic mastery_score. Returns the resulting mastery."""

    avg_flashcard_mastery = avg_flashcard_mastery_for_topic(connection, topic_id)
    if avg_flashcard_mastery is None:
        topic_row = get_topic(connection, topic_id)
        return float(topic_row.get("mastery_score") or 0.0) if topic_row else None

    topic_row = get_topic(connection, topic_id)
    existing_mastery = float(topic_row.get("mastery_score") or 0.0) if topic_row else 0.0
    blended = (
        (existing_mastery + avg_flashcard_mastery) / 2
        if existing_mastery > 0
        else avg_flashcard_mastery
    )
    blended = max(0.0, min(1.0, blended))
    set_topic_progress(connection, topic_id, mastery_score=blended)
    return blended


def review_flashcard(
    db_path, flashcard_id: str, confidence: str
) -> tuple[Flashcard, float | None, bool]:
    """Grade one flashcard review with SM-2, update mastery, and react via the planner.

    Returns (updated flashcard, topic mastery after rebalance, whether more cards were generated).
    """

    if confidence not in CONFIDENCE_QUALITY:
        raise ValueError(f"Unknown confidence rating: {confidence}")
    quality = CONFIDENCE_QUALITY[confidence]

    connection = connect_sqlite(db_path)
    try:
        ensure_study_tables(connection)
        row = get_flashcard(connection, flashcard_id)
        if row is None:
            raise ValueError(f"Unknown flashcard_id: {flashcard_id}")

        new_ease, new_interval, new_review_count = sm2_update(
            float(row["ease_factor"]), float(row["review_interval"]), int(row["review_count"]), quality
        )
        new_mastery = _next_mastery_weight(float(row["mastery_weight"]), quality)
        now = datetime.utcnow()
        next_review_date = (now + timedelta(days=new_interval)).date().isoformat()
        last_review_iso = now.isoformat()

        update_flashcard_review(
            connection,
            flashcard_id,
            ease_factor=new_ease,
            review_interval=new_interval,
            next_review=next_review_date,
            last_review=last_review_iso,
            review_count=new_review_count,
            mastery_weight=new_mastery,
        )

        topic_id = row.get("topic_id")
        topic_mastery: float | None = None
        if topic_id:
            topic_mastery = _rebalance_topic_mastery(connection, topic_id)

        connection.commit()

        updated_row = dict(row)
        updated_row.update(
            {
                "ease_factor": new_ease,
                "review_interval": new_interval,
                "next_review": next_review_date,
                "last_review": last_review_iso,
                "review_count": new_review_count,
                "mastery_weight": new_mastery,
            }
        )
    finally:
        connection.close()

    generated_more = False
    if topic_id and topic_mastery is not None:
        generated_more = _maybe_top_up_flashcards(db_path, topic_id, topic_mastery)

    return _row_to_flashcard(updated_row), topic_mastery, generated_more


def _maybe_top_up_flashcards(db_path, topic_id: str, mastery: float) -> bool:
    """Planner reaction: low mastery generates more cards; high mastery generates none."""

    if mastery >= HIGH_MASTERY_THRESHOLD:
        return False

    if mastery >= LOW_MASTERY_THRESHOLD:
        return False

    connection = connect_sqlite(db_path)
    try:
        ensure_study_tables(connection)
        existing = count_flashcards_for_topic(connection, topic_id)
    finally:
        connection.close()

    if existing >= DUE_CARD_FLOOR:
        return False

    try:
        generate_flashcards_for_workspace(db_path, topic_id=topic_id, count=TOPUP_BATCH_SIZE)
        return True
    except ValueError:
        return False
