"""Deterministic reranking and context budgeting."""

from __future__ import annotations

from collections import OrderedDict, defaultdict
from dataclasses import dataclass
from typing import Protocol

from backend.config import (
    EMBEDDING_MODEL,
    EMBEDDINGS_PROVIDER,
    MAX_CONTEXT_CHUNKS,
    MAX_CONTEXT_TOKENS,
    MAX_RETRIEVAL_CANDIDATES,
    validate_embedding_model_name,
    validate_embeddings_provider_name,
    validate_positive_int,
)
from backend.indexer.bm25 import RetrievalChunk
from backend.indexer.embeddings import EmbeddingService
from backend.indexer.vectors import cosine_similarity
from backend.telemetry.tracing import metrics_registry, trace_collector


@dataclass(frozen=True)
class RerankDecision:
    chunk: RetrievalChunk
    candidate_rank: int
    reranked_rank: int | None
    rerank_score: float
    selected: bool
    reason: str


@dataclass(frozen=True)
class RerankResult:
    selected_chunks: list[RetrievalChunk]
    decisions: list[RerankDecision]


class Reranker(Protocol):
    def rerank(
        self,
        query: str,
        candidates: list[RetrievalChunk],
        *,
        limit: int,
    ) -> RerankResult:
        """Rerank retrieved candidates into final grounded context."""


@dataclass
class DeterministicReranker:
    """Deterministic reranking independent from retrieval provider."""

    embedding_service: EmbeddingService | None = None
    max_retrieval_candidates: int | None = None
    max_context_chunks: int | None = None
    max_context_tokens: int | None = None

    def __post_init__(self) -> None:
        if self.embedding_service is None:
            self.embedding_service = EmbeddingService(
                provider_name=validate_embeddings_provider_name(EMBEDDINGS_PROVIDER),
                model_name=validate_embedding_model_name(EMBEDDING_MODEL),
            )
        if self.max_retrieval_candidates is None:
            self.max_retrieval_candidates = validate_positive_int(
                "FIELDNOTES_MAX_RETRIEVAL_CANDIDATES",
                MAX_RETRIEVAL_CANDIDATES,
            )
        if self.max_context_chunks is None:
            self.max_context_chunks = validate_positive_int(
                "FIELDNOTES_MAX_CONTEXT_CHUNKS",
                MAX_CONTEXT_CHUNKS,
            )
        if self.max_context_tokens is None:
            self.max_context_tokens = validate_positive_int(
                "FIELDNOTES_MAX_CONTEXT_TOKENS",
                MAX_CONTEXT_TOKENS,
            )

    def rerank(
        self,
        query: str,
        candidates: list[RetrievalChunk],
        *,
        limit: int,
    ) -> RerankResult:
        assert self.embedding_service is not None
        import time

        started = time.perf_counter()
        with trace_collector.span("reranking", query=query, candidate_count=len(candidates), limit=limit):
            query_vector = self.embedding_service.embed_query(query)
            query_tokens = _tokenize(query)
            candidate_limit = min(self.max_retrieval_candidates or len(candidates), len(candidates))

            deduped: OrderedDict[tuple[str, str], RetrievalChunk] = OrderedDict()
            decisions: list[RerankDecision] = []
            for candidate_rank, chunk in enumerate(candidates[:candidate_limit], start=1):
                key = (chunk.file_id, chunk.anchor)
                if key in deduped:
                    decisions.append(
                        RerankDecision(
                            chunk=_annotate_chunk(
                                chunk,
                                candidate_rank=candidate_rank,
                                rerank_score=float(chunk.diagnostics.get("fused_score", chunk.score)),
                                selected=False,
                                reason="duplicate_chunk",
                            ),
                            candidate_rank=candidate_rank,
                            reranked_rank=None,
                            rerank_score=float(chunk.diagnostics.get("fused_score", chunk.score)),
                            selected=False,
                            reason="duplicate_chunk",
                        )
                    )
                    continue
                deduped[key] = chunk

            scored: list[tuple[RetrievalChunk, float, int]] = []
            for candidate_rank, chunk in enumerate(deduped.values(), start=1):
                score = self._score_candidate(query_tokens, query_vector, chunk)
                scored.append(
                    (
                        _annotate_chunk(
                            chunk,
                            candidate_rank=candidate_rank,
                            rerank_score=score,
                            reason="candidate_pool",
                        ),
                        score,
                        candidate_rank,
                    )
                )

            scored.sort(
                key=lambda item: (
                    -item[1],
                    item[0].relative_path,
                    item[0].anchor,
                    item[0].chunk,
                )
            )

            grouped: dict[str, list[tuple[RetrievalChunk, float, int]]] = defaultdict(list)
            file_order: list[str] = []
            for item in scored:
                if item[0].relative_path not in grouped:
                    file_order.append(item[0].relative_path)
                grouped[item[0].relative_path].append(item)

            selected: list[RetrievalChunk] = []
            selected_anchor_bases: set[tuple[str, str]] = set()
            selected_text_keys: set[tuple[str, str]] = set()
            selected_original_keys: set[tuple[str, str]] = set()
            token_budget = self.max_context_tokens or 0
            chunk_budget = min(limit, self.max_context_chunks or limit)
            reranked_rank = 1

            while len(selected) < chunk_budget:
                progressed = False
                for file_path in file_order:
                    if len(selected) >= chunk_budget:
                        break
                    file_candidates = grouped[file_path]
                    while file_candidates:
                        chunk, score, candidate_rank = file_candidates.pop(0)
                        original_key = (chunk.file_id, chunk.anchor)
                        anchor_key = (chunk.file_id, _base_anchor(chunk.anchor))
                        text_key = (chunk.file_id, chunk.chunk.strip())
                        estimated_tokens = estimate_token_count(chunk.chunk)
                        if original_key in selected_original_keys:
                            decisions.append(
                                RerankDecision(chunk, candidate_rank, None, score, False, "duplicate_chunk")
                            )
                            continue
                        if anchor_key in selected_anchor_bases:
                            decisions.append(
                                RerankDecision(chunk, candidate_rank, None, score, False, "overlapping_anchor")
                            )
                            continue
                        if text_key in selected_text_keys:
                            decisions.append(
                                RerankDecision(chunk, candidate_rank, None, score, False, "duplicate_text")
                            )
                            continue
                        if token_budget - estimated_tokens < 0:
                            decisions.append(
                                RerankDecision(chunk, candidate_rank, None, score, False, "context_token_limit")
                            )
                            continue

                        selected_chunk = _annotate_chunk(
                            chunk,
                            candidate_rank=candidate_rank,
                            reranked_rank=reranked_rank,
                            rerank_score=score,
                            selected=True,
                            reason="selected_diverse_context",
                        )
                        selected.append(selected_chunk)
                        selected_anchor_bases.add(anchor_key)
                        selected_text_keys.add(text_key)
                        selected_original_keys.add(original_key)
                        token_budget -= estimated_tokens
                        decisions.append(
                            RerankDecision(
                                selected_chunk,
                                candidate_rank,
                                reranked_rank,
                                score,
                                True,
                                "selected_diverse_context",
                            )
                        )
                        reranked_rank += 1
                        progressed = True
                        break
                if not progressed:
                    break

            selected_keys = {(chunk.file_id, chunk.anchor) for chunk in selected}
            for chunk, score, candidate_rank in scored:
                key = (chunk.file_id, chunk.anchor)
                if key in selected_keys:
                    continue
                if any(
                    decision.chunk.file_id == chunk.file_id and decision.chunk.anchor == chunk.anchor
                    for decision in decisions
                ):
                    continue
                reason = "context_chunk_limit" if len(selected) >= chunk_budget else "diversity_not_selected"
                decisions.append(
                    RerankDecision(chunk, candidate_rank, None, score, False, reason)
                )

            metrics_registry.record("reranking_latency_ms", (time.perf_counter() - started) * 1000)
            return RerankResult(selected_chunks=selected, decisions=decisions)

    def _score_candidate(
        self,
        query_tokens: set[str],
        query_vector: list[float],
        chunk: RetrievalChunk,
    ) -> float:
        assert self.embedding_service is not None
        chunk_vector = self.embedding_service.embed_query(chunk.chunk)
        semantic_similarity = cosine_similarity(query_vector, chunk_vector)
        bm25_score = float(chunk.diagnostics.get("bm25_score", chunk.score or 0.0))
        vector_score = float(chunk.diagnostics.get("vector_score", 0.0))
        fused_score = float(chunk.diagnostics.get("fused_score", chunk.score or 0.0))
        exact_phrase = 1.0 if query_tokens and " ".join(sorted(query_tokens)) in chunk.chunk.lower() else 0.0
        overlap = concept_overlap(query_tokens, _tokenize(chunk.chunk))
        path_boost = concept_overlap(query_tokens, _tokenize(chunk.relative_path.replace("/", " ")))
        return (
            0.30 * semantic_similarity
            + 0.20 * bm25_score
            + 0.15 * vector_score
            + 0.15 * fused_score
            + 0.10 * overlap
            + 0.05 * exact_phrase
            + 0.05 * path_boost
        )


def estimate_token_count(text: str) -> int:
    """Use deterministic rough token estimate."""

    return max(1, len(text.split()))


def concept_overlap(left: set[str], right: set[str]) -> float:
    """Return Jaccard overlap for concept-like tokens."""

    if not left or not right:
        return 0.0
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)


def _tokenize(text: str) -> set[str]:
    return {token.lower() for token in text.split() if token.strip()}


def _base_anchor(anchor: str) -> str:
    return anchor.split("/b", 1)[0]


def _annotate_chunk(
    chunk: RetrievalChunk,
    *,
    candidate_rank: int,
    reranked_rank: int | None = None,
    rerank_score: float,
    selected: bool = False,
    reason: str,
) -> RetrievalChunk:
    diagnostics = dict(chunk.diagnostics)
    diagnostics.update(
        {
            "candidate_rank": candidate_rank,
            "reranked_rank": reranked_rank,
            "rerank_score": rerank_score,
            "selected": selected,
            "reason": reason,
        }
    )
    return RetrievalChunk(
        chunk=chunk.chunk,
        score=chunk.score,
        anchor=chunk.anchor,
        file_id=chunk.file_id,
        relative_path=chunk.relative_path,
        diagnostics=diagnostics,
    )
