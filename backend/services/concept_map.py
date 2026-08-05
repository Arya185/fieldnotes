"""Build a concept map graph from the workspace's concept log.

Nodes are concepts logged during ask/quiz activity (`concepts` table). Edges
are co-occurrence: two concepts logged under the same answer (grounded
answer or quiz attempt), or against the same source document, are connected.
This is a plain node/edge JSON structure — rendering is a frontend concern.
"""

from __future__ import annotations

import sqlite3
from collections import Counter, defaultdict
from itertools import combinations
from typing import Any

from backend.storage import ensure_concept_occurrences_table


def _file_id_from_anchor(source_anchor: str | None) -> str | None:
    if not source_anchor or "#" not in source_anchor:
        return None
    return source_anchor.split("#", 1)[0]


def build_concept_map(connection: sqlite3.Connection) -> dict[str, Any]:
    """Build the concept map graph for one workspace."""

    ensure_concept_occurrences_table(connection)

    concept_rows = connection.execute(
        "SELECT id, name, state, source_anchor FROM concepts ORDER BY name"
    ).fetchall()
    nodes = [
        {
            "id": str(row["id"]),
            "name": str(row["name"]),
            "state": str(row["state"]),
            "source_anchor": row["source_anchor"],
        }
        for row in concept_rows
    ]
    known_concept_ids = {node["id"] for node in nodes}

    occurrence_rows = connection.execute(
        "SELECT concept_id, answer_id, source_anchor FROM concept_occurrences"
    ).fetchall()

    by_answer: dict[str, set[str]] = defaultdict(set)
    by_document: dict[str, set[str]] = defaultdict(set)
    for row in occurrence_rows:
        concept_id = str(row["concept_id"])
        if concept_id not in known_concept_ids:
            continue
        answer_id = row["answer_id"]
        if answer_id:
            by_answer[str(answer_id)].add(concept_id)
        file_id = _file_id_from_anchor(row["source_anchor"])
        if file_id:
            by_document[file_id].add(concept_id)

    edge_weights: Counter[tuple[str, str]] = Counter()
    edge_reasons: dict[tuple[str, str], set[str]] = defaultdict(set)
    for groups, reason in ((by_answer.values(), "answer"), (by_document.values(), "document")):
        for concept_ids in groups:
            for concept_a, concept_b in combinations(sorted(concept_ids), 2):
                key = (concept_a, concept_b)
                edge_weights[key] += 1
                edge_reasons[key].add(reason)

    edges = [
        {
            "source": source,
            "target": target,
            "weight": weight,
            "reasons": sorted(edge_reasons[(source, target)]),
        }
        for (source, target), weight in edge_weights.items()
    ]

    return {"nodes": nodes, "edges": edges}
