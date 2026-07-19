"""SQLite-backed BM25 retrieval provider."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Protocol

from rank_bm25 import BM25Okapi


TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_]+(?:-[A-Za-z0-9_]+)*")


@dataclass(frozen=True)
class RetrievalChunk:
    chunk: str
    score: float
    anchor: str
    file_id: str
    relative_path: str
    diagnostics: dict[str, Any] = field(default_factory=dict, compare=False, repr=False)


class RetrievalProvider(Protocol):
    def search(self, query: str, limit: int = 5) -> list[RetrievalChunk]:
        """Return ranked retrieval results for query."""


def tokenize(text: str) -> list[str]:
    """Tokenize text for deterministic BM25 ranking."""

    return TOKEN_PATTERN.findall(text.lower())


@dataclass(frozen=True)
class StoredChunk:
    text: str
    anchor: str
    file_id: str
    relative_path: str


class BM25Provider:
    """BM25 provider over persisted SQLite chunks."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def search(self, query: str, limit: int = 5) -> list[RetrievalChunk]:
        """Load persisted chunks from SQLite and rank them with BM25."""

        results: list[RetrievalChunk] = []
        for stored_chunk, score in self.score_chunks(query):
            if score <= 0:
                continue
            results.append(
                RetrievalChunk(
                    chunk=stored_chunk.text,
                    score=float(score),
                    anchor=stored_chunk.anchor,
                    file_id=stored_chunk.file_id,
                    relative_path=stored_chunk.relative_path,
                    diagnostics={"method": "bm25", "bm25_score": float(score)},
                )
            )
            if len(results) >= limit:
                break

        return results

    def score_chunks(self, query: str) -> list[tuple[StoredChunk, float]]:
        """Return raw BM25 scores for all persisted chunks."""

        stored_chunks = self._load_chunks()
        if not stored_chunks:
            return []

        tokenized_corpus = [tokenize(chunk.text) for chunk in stored_chunks]
        bm25 = BM25Okapi(tokenized_corpus)
        query_tokens = tokenize(query)
        if not query_tokens:
            return []

        scores = bm25.get_scores(query_tokens)
        return sorted(
            [
                (stored_chunk, float(score))
                for stored_chunk, score in zip(stored_chunks, scores, strict=True)
            ],
            key=lambda item: item[1],
            reverse=True,
        )

    def _load_chunks(self) -> list[StoredChunk]:
        rows = self.connection.execute(
            """
            SELECT chunks.text, chunks.anchor, chunks.file_id, files.path AS relative_path
            FROM chunks
            JOIN files ON files.id = chunks.file_id
            ORDER BY file_id, ordinal
            """
        ).fetchall()
        return [
            StoredChunk(
                text=row["text"],
                anchor=row["anchor"],
                file_id=row["file_id"],
                relative_path=row["relative_path"],
            )
            for row in rows
        ]
