from __future__ import annotations

import sqlite3

from backend.indexer.bm25 import RetrievalChunk


def load_fallback_retrieval(
    connection: sqlite3.Connection,
    limit: int,
) -> list[RetrievalChunk]:
    rows = connection.execute(
        """
        SELECT chunks.text, chunks.anchor, chunks.file_id, files.path AS relative_path
        FROM chunks
        JOIN files ON files.id = chunks.file_id
        ORDER BY files.path, chunks.ordinal
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [
        RetrievalChunk(
            chunk=str(row["text"]),
            score=0.0,
            anchor=str(row["anchor"]),
            file_id=str(row["file_id"]),
            relative_path=str(row["relative_path"]),
        )
        for row in rows
    ]


def source_label(relative_path: str, locator: str) -> str:
    return f"{relative_path} {locator}"
