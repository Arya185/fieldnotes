"""Vector and hybrid retrieval providers."""

from __future__ import annotations

import math
import sqlite3
import time
from dataclasses import dataclass
from typing import Protocol

from backend.config import (
    BM25_WEIGHT,
    EMBEDDING_MODEL,
    EMBEDDINGS_PROVIDER,
    RETRIEVAL_PROVIDER,
    VECTOR_WEIGHT,
    validate_embedding_model_name,
    validate_embeddings_provider_name,
    validate_fusion_weight,
    validate_retrieval_provider_name,
)
from backend.indexer.bm25 import BM25Provider, RetrievalChunk, RetrievalProvider, StoredChunk
from backend.indexer.embeddings import EmbeddingService
from backend.storage import load_chunk_embeddings
from backend.telemetry.tracing import metrics_registry, trace_collector


class VectorProvider(Protocol):
    def search(self, query: str, limit: int = 5) -> list[RetrievalChunk]:
        """Return ranked vector retrieval results for query."""


@dataclass(frozen=True)
class ScoredChunk:
    chunk: str
    anchor: str
    file_id: str
    relative_path: str
    bm25_score: float = 0.0
    vector_score: float = 0.0
    fused_score: float = 0.0


@dataclass
class SQLiteVectorProvider:
    """SQLite vector retrieval over persisted embedding rows."""

    connection: sqlite3.Connection
    embedding_service: EmbeddingService | None = None

    def __post_init__(self) -> None:
        if self.embedding_service is None:
            self.embedding_service = EmbeddingService(
                provider_name=validate_embeddings_provider_name(EMBEDDINGS_PROVIDER),
                model_name=validate_embedding_model_name(EMBEDDING_MODEL),
            )

    def search(self, query: str, limit: int = 5) -> list[RetrievalChunk]:
        started = time.perf_counter()
        with trace_collector.span("retrieval", method="vector", query=query, limit=limit):
            scored = self.score_chunks(query)
            metrics_registry.record("retrieval_latency_ms", (time.perf_counter() - started) * 1000)
            return [
                RetrievalChunk(
                    chunk=item.chunk,
                    score=item.vector_score,
                    anchor=item.anchor,
                    file_id=item.file_id,
                    relative_path=item.relative_path,
                    diagnostics={
                        "method": "vector",
                        "vector_score": item.vector_score,
                        "fused_score": item.vector_score,
                    },
                )
                for item in scored[:limit]
            ]

    def score_chunks(self, query: str) -> list[ScoredChunk]:
        assert self.embedding_service is not None
        query_vector = self.embedding_service.embed_query(query)
        stored = load_chunk_embeddings(
            self.connection,
            provider=self.embedding_service.provider_name,
            model=self.embedding_service.model_name,
        )
        ranked: list[ScoredChunk] = []
        for chunk, vector in stored:
            similarity = cosine_similarity(query_vector, vector)
            if similarity <= 0:
                continue
            ranked.append(
                ScoredChunk(
                    chunk=chunk.text,
                    anchor=chunk.anchor,
                    file_id=chunk.file_id,
                    relative_path=chunk.relative_path,
                    vector_score=similarity,
                    fused_score=similarity,
                )
            )
        ranked.sort(key=lambda item: item.vector_score, reverse=True)
        return ranked


@dataclass
class HybridProvider:
    """Hybrid retrieval over BM25 and persisted embeddings."""

    connection: sqlite3.Connection
    mode: str = "hybrid"
    embedding_service: EmbeddingService | None = None
    bm25_weight: float | None = None
    vector_weight: float | None = None

    def __post_init__(self) -> None:
        self.bm25 = BM25Provider(self.connection)
        self.vector = SQLiteVectorProvider(self.connection, embedding_service=self.embedding_service)
        self.bm25_weight = (
            validate_fusion_weight("FIELDNOTES_BM25_WEIGHT", BM25_WEIGHT)
            if self.bm25_weight is None
            else self.bm25_weight
        )
        self.vector_weight = (
            validate_fusion_weight("FIELDNOTES_VECTOR_WEIGHT", VECTOR_WEIGHT)
            if self.vector_weight is None
            else self.vector_weight
        )

    def search(self, query: str, limit: int = 5) -> list[RetrievalChunk]:
        started = time.perf_counter()
        if self.mode == "vector":
            return self.vector.search(query=query, limit=limit)
        if self.mode == "bm25":
            return self.bm25.search(query=query, limit=limit)

        with trace_collector.span("retrieval", method="hybrid", query=query, limit=limit):
            fused = self.score_chunks(query)
            metrics_registry.record("retrieval_latency_ms", (time.perf_counter() - started) * 1000)
            return [
                RetrievalChunk(
                    chunk=item.chunk,
                    score=item.fused_score,
                    anchor=item.anchor,
                    file_id=item.file_id,
                    relative_path=item.relative_path,
                    diagnostics={
                        "method": "hybrid",
                        "bm25_score": item.bm25_score,
                        "vector_score": item.vector_score,
                        "fused_score": item.fused_score,
                    },
                )
                for item in fused[:limit]
            ]

    def score_chunks(self, query: str) -> list[ScoredChunk]:
        bm25_rows = self.bm25.score_chunks(query)
        vector_rows = self.vector.score_chunks(query)

        bm25_scores = {
            _stored_chunk_key(chunk): score
            for chunk, score in bm25_rows
        }
        vector_scores = {
            (item.file_id, item.anchor): item.vector_score
            for item in vector_rows
        }
        chunk_index = {
            _stored_chunk_key(chunk): chunk
            for chunk, _score in bm25_rows
        }
        for item in vector_rows:
            key = (item.file_id, item.anchor)
            if key not in chunk_index:
                chunk_index[key] = StoredChunk(
                    text=item.chunk,
                    anchor=item.anchor,
                    file_id=item.file_id,
                    relative_path=item.relative_path,
                )

        normalized_bm25 = min_max_normalize(bm25_scores)
        normalized_vector = min_max_normalize(vector_scores)
        total_weight = self.bm25_weight + self.vector_weight
        effective_bm25 = self.bm25_weight / total_weight if total_weight > 0 else 0.5
        effective_vector = self.vector_weight / total_weight if total_weight > 0 else 0.5

        fused: list[ScoredChunk] = []
        for key, chunk in chunk_index.items():
            bm25_score = bm25_scores.get(key, 0.0)
            vector_score = vector_scores.get(key, 0.0)
            fused_score = (
                effective_bm25 * normalized_bm25.get(key, 0.0)
                + effective_vector * normalized_vector.get(key, 0.0)
            )
            if fused_score <= 0:
                continue
            fused.append(
                ScoredChunk(
                    chunk=chunk.text,
                    anchor=chunk.anchor,
                    file_id=chunk.file_id,
                    relative_path=chunk.relative_path,
                    bm25_score=bm25_score,
                    vector_score=vector_score,
                    fused_score=fused_score,
                )
            )
        fused.sort(key=lambda item: item.fused_score, reverse=True)
        return fused


def get_retrieval_provider(connection: sqlite3.Connection) -> RetrievalProvider:
    """Select retrieval provider from configuration."""

    provider_name = validate_retrieval_provider_name(RETRIEVAL_PROVIDER)
    if provider_name == "bm25":
        return BM25Provider(connection)
    if provider_name == "vector":
        return HybridProvider(connection, mode="vector")
    return HybridProvider(connection, mode="hybrid")


def cosine_similarity(left: list[float], right: list[float]) -> float:
    """Compute cosine similarity for equal-length vectors."""

    if len(left) != len(right) or not left:
        return 0.0
    dot = sum(l * r for l, r in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(l * l for l in left))
    right_norm = math.sqrt(sum(r * r for r in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def min_max_normalize(scores: dict[tuple[str, str], float]) -> dict[tuple[str, str], float]:
    """Normalize score range to [0, 1]."""

    if not scores:
        return {}
    minimum = min(scores.values())
    maximum = max(scores.values())
    if maximum == minimum:
        return {key: 1.0 if value > 0 else 0.0 for key, value in scores.items()}
    return {
        key: (value - minimum) / (maximum - minimum)
        for key, value in scores.items()
    }


def _stored_chunk_key(chunk: StoredChunk) -> tuple[str, str]:
    return chunk.file_id, chunk.anchor
