"""Persistence helpers for Phase 1 indexing artifacts."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator
from uuid import uuid4

from backend.indexer.chunking import ChunkCandidate
from backend.indexer.parsers import ParsedFile
from backend.models import ArtifactCard, CitationChip, ConceptUpdate, DatasetProfile


@dataclass(frozen=True)
class PersistedChunk:
    id: str
    file_id: str
    ordinal: int
    text: str
    anchor: str
    relative_path: str = ""


@dataclass(frozen=True)
class PersistedEmbedding:
    chunk_id: str
    provider: str
    model: str
    content_hash: str
    vector: list[float]


def utc_now_iso() -> str:
    """Return current UTC timestamp in ISO 8601 format."""

    return datetime.now(UTC).isoformat()


def stable_id(prefix: str, value: str) -> str:
    """Generate stable ID for repeatable indexing runs."""

    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()
    return f"{prefix}_{digest[:24]}"


def file_id_for_path(relative_path: str) -> str:
    return stable_id("file", relative_path)


def chunk_id_for_anchor(relative_path: str, ordinal: int, anchor: str) -> str:
    return stable_id("chunk", f"{relative_path}:{ordinal}:{anchor}")


def chunk_content_hash(text: str) -> str:
    """Generate stable content hash for incremental embedding regeneration."""

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@contextmanager
def indexing_transaction(connection: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Wrap one indexing run in a single transaction."""

    try:
        connection.execute("BEGIN")
        yield connection
    except Exception:
        connection.rollback()
        raise
    else:
        connection.commit()


def replace_file_record(connection: sqlite3.Connection, parsed_file: ParsedFile) -> str:
    """Replace persisted record for one file path and return stable file ID."""

    file_id = file_id_for_path(parsed_file.relative_path)
    connection.execute("DELETE FROM files WHERE path = ?", (parsed_file.relative_path,))
    connection.execute(
        """
        INSERT INTO files (
          id, path, kind, display_name, size_bytes, parse_status, parse_summary, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            file_id,
            parsed_file.relative_path,
            parsed_file.kind,
            parsed_file.display_name,
            parsed_file.size_bytes,
            parsed_file.parse_status,
            summarize_parsed_file(parsed_file),
            utc_now_iso(),
        ),
    )
    return file_id


def replace_chunks(
    connection: sqlite3.Connection,
    file_id: str,
    relative_path: str,
    chunks: list[ChunkCandidate],
) -> list[PersistedChunk]:
    """Replace all chunks for one file."""

    connection.execute("DELETE FROM chunks WHERE file_id = ?", (file_id,))
    if not chunks:
        return []

    persisted_chunks = [
        PersistedChunk(
            id=chunk_id_for_anchor(relative_path, chunk.ordinal, chunk.anchor),
            file_id=file_id,
            ordinal=chunk.ordinal,
            text=chunk.text,
            anchor=chunk.anchor,
            relative_path=relative_path,
        )
        for chunk in chunks
    ]

    connection.executemany(
        """
        INSERT INTO chunks (id, file_id, ordinal, text, anchor)
        VALUES (?, ?, ?, ?, ?)
        """,
        [
            (chunk.id, chunk.file_id, chunk.ordinal, chunk.text, chunk.anchor)
            for chunk in persisted_chunks
        ],
    )
    return persisted_chunks


def replace_dataset_profile(
    connection: sqlite3.Connection,
    file_id: str,
    dataset_profile: DatasetProfile | None,
) -> None:
    """Replace dataset profile for one file when available."""

    connection.execute("DELETE FROM dataset_profiles WHERE file_id = ?", (file_id,))
    if dataset_profile is None:
        return

    connection.execute(
        """
        INSERT INTO dataset_profiles (file_id, profile_json)
        VALUES (?, ?)
        """,
        (file_id, dataset_profile.model_dump_json()),
    )


def load_dataset_profiles(connection: sqlite3.Connection) -> list[DatasetProfile]:
    """Load all persisted dataset profiles."""

    rows = connection.execute(
        """
        SELECT dataset_profiles.profile_json
        FROM dataset_profiles
        JOIN files ON files.id = dataset_profiles.file_id
        ORDER BY files.path
        """
    ).fetchall()
    return [DatasetProfile.model_validate_json(str(row["profile_json"])) for row in rows]


def upsert_workspace_meta(connection: sqlite3.Connection, key: str, value: str) -> None:
    """Insert or replace one workspace metadata value."""

    connection.execute(
        """
        INSERT INTO workspace_meta (key, value)
        VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (key, value),
    )


def persist_indexing_result(
    connection: sqlite3.Connection,
    parsed_file: ParsedFile,
    chunks: list[ChunkCandidate],
) -> tuple[str, list[PersistedChunk]]:
    """Persist one file, its chunks, and optional dataset profile."""

    file_id = replace_file_record(connection, parsed_file)
    persisted_chunks = replace_chunks(connection, file_id, parsed_file.relative_path, chunks)
    replace_dataset_profile(
        connection,
        file_id,
        parsed_file.content.dataset_profile if parsed_file.content else None,
    )
    return file_id, persisted_chunks


def summarize_parsed_file(parsed_file: ParsedFile) -> str | None:
    """Build lightweight parse summary for files table."""

    if parsed_file.parse_status != "parsed":
        return parsed_file.error_message

    content = parsed_file.content
    if content is None:
        return None

    if content.dataset_profile is not None:
        dataset_profile = content.dataset_profile
        return f"{dataset_profile.row_count} rows, {len(dataset_profile.columns)} columns"

    if content.segments:
        return f"{len(content.segments)} sections parsed"

    if content.text:
        return "text parsed"

    return None


def load_file_paths_by_ids(connection: sqlite3.Connection, file_ids: list[str]) -> dict[str, str]:
    """Load relative file paths for a set of file IDs."""

    if not file_ids:
        return {}

    placeholders = ",".join(["?"] * len(file_ids))
    rows = connection.execute(
        f"SELECT id, path FROM files WHERE id IN ({placeholders})",
        file_ids,
    ).fetchall()
    return {row["id"]: row["path"] for row in rows}


def load_file_path_by_id(connection: sqlite3.Connection, file_id: str) -> str | None:
    """Load one relative file path by file ID."""

    row = connection.execute("SELECT path FROM files WHERE id = ?", (file_id,)).fetchone()
    return None if row is None else str(row["path"])


def load_chunk_by_anchor(
    connection: sqlite3.Connection, file_id: str, anchor: str
) -> sqlite3.Row | None:
    """Load one persisted chunk by file and anchor."""

    return connection.execute(
        "SELECT id, text, anchor, file_id FROM chunks WHERE file_id = ? AND anchor = ?",
        (file_id, anchor),
    ).fetchone()


def load_chunks_for_file(connection: sqlite3.Connection, file_id: str) -> list[PersistedChunk]:
    """Load persisted chunks for one file in stable ordinal order."""

    rows = connection.execute(
        """
        SELECT id, file_id, ordinal, text, anchor
        FROM chunks
        WHERE file_id = ?
        ORDER BY ordinal
        """,
        (file_id,),
    ).fetchall()
    return [
        PersistedChunk(
            id=str(row["id"]),
            file_id=str(row["file_id"]),
            ordinal=int(row["ordinal"]),
            text=str(row["text"]),
            anchor=str(row["anchor"]),
            relative_path="",
        )
        for row in rows
    ]


def load_embedding_hashes(
    connection: sqlite3.Connection,
    chunk_ids: list[str],
    provider: str,
    model: str,
) -> dict[str, str]:
    """Load persisted embedding hashes keyed by chunk ID."""

    if not chunk_ids:
        return {}

    placeholders = ",".join(["?"] * len(chunk_ids))
    rows = connection.execute(
        f"""
        SELECT chunk_id, content_hash
        FROM embeddings
        WHERE provider = ? AND model = ? AND chunk_id IN ({placeholders})
        """,
        [provider, model, *chunk_ids],
    ).fetchall()
    return {str(row["chunk_id"]): str(row["content_hash"]) for row in rows}


def load_chunk_embeddings(
    connection: sqlite3.Connection,
    *,
    provider: str,
    model: str,
) -> list[tuple[PersistedChunk, list[float]]]:
    """Load persisted chunk embeddings with chunk metadata."""

    rows = connection.execute(
        """
        SELECT
          chunks.id,
          chunks.file_id,
          chunks.ordinal,
          chunks.text,
          chunks.anchor,
          files.path AS relative_path,
          embeddings.vector_json
        FROM embeddings
        JOIN chunks ON chunks.id = embeddings.chunk_id
        JOIN files ON files.id = chunks.file_id
        WHERE embeddings.provider = ? AND embeddings.model = ?
        ORDER BY files.path, chunks.ordinal
        """,
        (provider, model),
    ).fetchall()
    results: list[tuple[PersistedChunk, list[float]]] = []
    for row in rows:
        chunk = PersistedChunk(
            id=str(row["id"]),
            file_id=str(row["file_id"]),
            ordinal=int(row["ordinal"]),
            text=str(row["text"]),
            anchor=str(row["anchor"]),
            relative_path=str(row["relative_path"]),
        )
        vector = [float(value) for value in json.loads(str(row["vector_json"]))]
        results.append((chunk, vector))
    return results


def select_chunks_requiring_embeddings(
    connection: sqlite3.Connection,
    chunks: list[PersistedChunk],
    *,
    provider: str,
    model: str,
) -> list[PersistedChunk]:
    """Return only chunks with missing or stale embeddings for this provider/model."""

    persisted_hashes = load_embedding_hashes(
        connection,
        [chunk.id for chunk in chunks],
        provider,
        model,
    )
    return [
        chunk
        for chunk in chunks
        if persisted_hashes.get(chunk.id) != chunk_content_hash(chunk.text)
    ]


def upsert_embeddings(
    connection: sqlite3.Connection,
    embeddings: list[PersistedEmbedding],
) -> None:
    """Insert or replace chunk embeddings without touching chunk text."""

    if not embeddings:
        return

    connection.executemany(
        """
        INSERT INTO embeddings (
          chunk_id, provider, model, content_hash, vector_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(chunk_id) DO UPDATE SET
          provider = excluded.provider,
          model = excluded.model,
          content_hash = excluded.content_hash,
          vector_json = excluded.vector_json,
          created_at = excluded.created_at
        """,
        [
            (
                embedding.chunk_id,
                embedding.provider,
                embedding.model,
                embedding.content_hash,
                json.dumps(embedding.vector),
                utc_now_iso(),
            )
            for embedding in embeddings
        ],
    )


def validate_citation_anchors(
    connection: sqlite3.Connection, chips: list[CitationChip]
) -> list[CitationChip]:
    """Keep only document citations that resolve to persisted chunks."""

    valid: list[CitationChip] = []
    for chip in chips:
        if chip.anchor is None:
            valid.append(chip)
            continue
        if "#" not in chip.anchor:
            continue
        file_id, anchor = chip.anchor.split("#", 1)
        if load_chunk_by_anchor(connection, file_id, anchor) is not None:
            valid.append(chip)
    return valid


def upsert_concept_updates(
    connection: sqlite3.Connection,
    updates: list[ConceptUpdate],
    source_anchor: str | None = None,
) -> None:
    """Persist concept state updates."""

    for update in updates:
        existing = connection.execute(
            "SELECT touch_count, miss_count FROM concepts WHERE id = ?",
            (update.concept_id,),
        ).fetchone()
        if existing is None:
            touch_count = 1
            miss_count = 1 if update.state == "shaky" else 0
            next_state = update.state
            connection.execute(
                """
                INSERT INTO concepts (
                  id, name, state, touch_count, miss_count, source_anchor, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    update.concept_id,
                    update.name,
                    next_state,
                    touch_count,
                    miss_count,
                    source_anchor,
                    utc_now_iso(),
                ),
            )
        else:
            touch_count = int(existing["touch_count"]) + 1
            next_state = update.state
            if update.state == "touched" and int(existing["touch_count"]) >= 1:
                next_state = "shaky"
            miss_count = int(existing["miss_count"]) + (1 if next_state == "shaky" else 0)
            connection.execute(
                """
                UPDATE concepts
                SET name = ?, state = ?, touch_count = ?, miss_count = ?, source_anchor = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    update.name,
                    next_state,
                    touch_count,
                    miss_count,
                    source_anchor,
                    utc_now_iso(),
                    update.concept_id,
                ),
            )


def create_artifact(
    connection: sqlite3.Connection,
    artifacts_dir: Path,
    *,
    kind: str,
    title: str,
    answer_id: str,
    payload_text: str | None = None,
    file_contents: str | None = None,
    file_extension: str | None = None,
    existing_file_path: Path | None = None,
) -> ArtifactCard:
    """Persist artifact metadata and optional file payload."""

    artifact_id = f"artifact_{uuid4()}"
    payload_path = None
    url = None
    if existing_file_path is not None:
        payload_path = str(existing_file_path)
        url = str(existing_file_path)
    elif file_contents is not None and file_extension is not None:
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = artifacts_dir / f"{artifact_id}.{file_extension}"
        artifact_path.write_text(file_contents, encoding="utf-8")
        payload_path = str(artifact_path)
        url = str(artifact_path)

    created_at = utc_now_iso()
    connection.execute(
        """
        INSERT INTO artifacts (id, kind, title, payload_path, payload_text, answer_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (artifact_id, kind, title, payload_path, payload_text, answer_id, created_at),
    )
    return ArtifactCard(
        id=artifact_id,
        kind=kind,
        title=title,
        created_at=created_at,
        url=url,
    )


def load_all_artifacts(connection: sqlite3.Connection) -> list[ArtifactCard]:
    """Load notebook artifact cards in reverse chronological order."""

    rows = connection.execute(
        """
        SELECT id, kind, title, created_at, payload_path
        FROM artifacts
        ORDER BY created_at DESC, id DESC
        """
    ).fetchall()
    return [
        ArtifactCard(
            id=row["id"],
            kind=row["kind"],
            title=row["title"],
            created_at=row["created_at"],
            url=row["payload_path"],
        )
        for row in rows
    ]


def load_artifact_row(connection: sqlite3.Connection, artifact_id: str) -> sqlite3.Row | None:
    """Load raw artifact storage record."""

    return connection.execute(
        """
        SELECT id, kind, title, payload_path, payload_text, answer_id, created_at
        FROM artifacts
        WHERE id = ?
        """,
        (artifact_id,),
    ).fetchone()


def create_quiz_attempt(
    connection: sqlite3.Connection,
    *,
    concept_id: str,
    question: str,
    options: list[str],
    correct_index: int,
    source_anchor: str,
) -> str:
    """Persist one quiz attempt and return attempt ID."""

    attempt_id = f"attempt_{uuid4()}"
    connection.execute(
        """
        INSERT INTO quiz_attempts (
          id, concept_id, question, options_json, correct_index, chosen_index, is_correct, source_anchor, created_at
        ) VALUES (?, ?, ?, ?, ?, NULL, NULL, ?, ?)
        """,
        (
            attempt_id,
            concept_id,
            question,
            json.dumps(options),
            correct_index,
            source_anchor,
            utc_now_iso(),
        ),
    )
    return attempt_id


def load_quiz_attempt(connection: sqlite3.Connection, attempt_id: str) -> sqlite3.Row | None:
    """Load persisted quiz attempt."""

    return connection.execute(
        """
        SELECT qa.*, c.name AS concept_name
        FROM quiz_attempts qa
        JOIN concepts c ON c.id = qa.concept_id
        WHERE qa.id = ?
        """,
        (attempt_id,),
    ).fetchone()


def record_quiz_answer(
    connection: sqlite3.Connection, attempt_id: str, chosen_index: int
) -> sqlite3.Row | None:
    """Persist chosen answer and correctness."""

    attempt = load_quiz_attempt(connection, attempt_id)
    if attempt is None:
        return None
    if attempt["chosen_index"] is not None:
        raise ValueError(f"Quiz attempt already answered: {attempt_id}")

    is_correct = int(chosen_index == int(attempt["correct_index"]))
    connection.execute(
        """
        UPDATE quiz_attempts
        SET chosen_index = ?, is_correct = ?
        WHERE id = ?
        """,
        (chosen_index, is_correct, attempt_id),
    )
    return load_quiz_attempt(connection, attempt_id)
