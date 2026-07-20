from __future__ import annotations

import sqlite3

from backend.models import StarterCard
from backend.storage import load_file_path_by_id


def build_refreshed_starters(connection: sqlite3.Connection) -> list[StarterCard]:
    rows = connection.execute(
        """
        SELECT id, name, state, source_anchor
        FROM concepts
        ORDER BY CASE state WHEN 'shaky' THEN 0 ELSE 1 END, updated_at DESC
        LIMIT 4
        """
    ).fetchall()
    starters: list[StarterCard] = []
    for row in rows:
        file_path = ""
        source_anchor = row["source_anchor"]
        if source_anchor and "#" in str(source_anchor):
            file_id, _anchor = str(source_anchor).split("#", 1)
            file_path = load_file_path_by_id(connection, file_id) or ""
        starters.append(
            StarterCard(
                text=f"Review concept: {row['name']}",
                file_path=file_path,
                seed="practice" if row["state"] == "shaky" else "concept",
            )
        )
    return starters
