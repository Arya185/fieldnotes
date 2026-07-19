"""Internal retrieval inspection utilities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.indexer.bm25 import RetrievalChunk
from backend.indexer.reranker import RerankResult


@dataclass(frozen=True)
class RetrievalInspection:
    candidate_chunks: list[dict[str, Any]]
    reranked_chunks: list[dict[str, Any]]
    discarded_chunks: list[dict[str, Any]]
    final_context: list[dict[str, Any]]


def inspect_retrieval(
    candidates: list[RetrievalChunk],
    rerank_result: RerankResult,
) -> RetrievalInspection:
    selected_keys = {(chunk.file_id, chunk.anchor) for chunk in rerank_result.selected_chunks}
    reranked = [_row(chunk) for chunk in rerank_result.selected_chunks]
    discarded = [
        _decision_row(decision)
        for decision in rerank_result.decisions
        if not decision.selected
    ]
    return RetrievalInspection(
        candidate_chunks=[_row(chunk) for chunk in candidates],
        reranked_chunks=reranked,
        discarded_chunks=discarded,
        final_context=reranked,
    )


def _row(chunk: RetrievalChunk) -> dict[str, Any]:
    return {
        "file_id": chunk.file_id,
        "relative_path": chunk.relative_path,
        "anchor": chunk.anchor,
        "chunk": chunk.chunk,
        "score": chunk.score,
        "diagnostics": dict(chunk.diagnostics),
    }


def _decision_row(decision) -> dict[str, Any]:
    row = _row(decision.chunk)
    row.update(
        {
            "candidate_rank": decision.candidate_rank,
            "reranked_rank": decision.reranked_rank,
            "rerank_score": decision.rerank_score,
            "selected": decision.selected,
            "reason": decision.reason,
        }
    )
    return row
