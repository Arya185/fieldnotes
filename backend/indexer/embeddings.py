"""Local embedding generation for persisted chunks."""

from __future__ import annotations

import hashlib
from collections import OrderedDict
from dataclasses import dataclass, field
from threading import Lock
from typing import Protocol

from backend.config import (
    EMBEDDING_MODEL,
    EMBEDDINGS_PROVIDER,
    validate_embedding_model_name,
    validate_embeddings_provider_name,
)
from backend.storage import PersistedChunk, PersistedEmbedding, chunk_content_hash


EMBEDDING_DIMENSIONS = 24
QUERY_EMBEDDING_CACHE_SIZE = 128
FASTEMBED_MODEL_NAME = "BAAI/bge-small-en-v1.5"
_FASTEMBED_MODELS: dict[str, object] = {}
_FASTEMBED_MODEL_LOCK = Lock()


class EmbeddingProvider(Protocol):
    def embed(self, text: str, *, model: str) -> list[float]:
        """Return embedding vector for text."""


@dataclass(frozen=True)
class DeterministicEmbeddingProvider:
    """Local hash-based lexical fallback for CI-stable non-semantic vectors."""

    dimensions: int = EMBEDDING_DIMENSIONS

    def embed(self, text: str, *, model: str) -> list[float]:
        values = [0.0] * self.dimensions
        normalized = text.lower().strip()
        tokens = normalized.split() or [normalized]
        for token in tokens:
            digest = hashlib.sha256(f"{model}\0{token}".encode("utf-8")).digest()
            slot = int.from_bytes(digest[:4], byteorder="big", signed=False) % self.dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            magnitude = (digest[5] / 255.0) + 0.1
            values[slot] += sign * magnitude
        return values


@dataclass(frozen=True)
class FastEmbedProvider:
    """CPU local semantic embedding provider backed by fastembed."""

    default_model: str = FASTEMBED_MODEL_NAME

    def embed(self, text: str, *, model: str) -> list[float]:
        normalized_model = model.strip()
        if not normalized_model or normalized_model == "hash-v1":
            normalized_model = self.default_model
        embedding_model = _load_fastembed_model(normalized_model)
        vector = next(iter(embedding_model.embed([text])))
        return [float(value) for value in vector.tolist()]


def build_embedding_provider(name: str) -> EmbeddingProvider:
    """Construct embedding provider from validated configuration."""

    provider_name = validate_embeddings_provider_name(name)
    if provider_name == "deterministic":
        return DeterministicEmbeddingProvider()
    if provider_name == "fastembed":
        return FastEmbedProvider()
    raise ValueError(f"Unsupported embedding provider: {provider_name}")


@dataclass(frozen=True)
class EmbeddingService:
    """Generate provider-scoped persisted embeddings for changed chunks only."""

    provider_name: str = EMBEDDINGS_PROVIDER
    model_name: str = EMBEDDING_MODEL
    query_cache_size: int = QUERY_EMBEDDING_CACHE_SIZE
    _query_cache: OrderedDict[tuple[str, str, str], list[float]] = field(
        default_factory=OrderedDict,
        init=False,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "provider_name",
            validate_embeddings_provider_name(self.provider_name),
        )
        object.__setattr__(
            self,
            "model_name",
            validate_embedding_model_name(self.model_name),
        )
        object.__setattr__(
            self,
            "_provider",
            build_embedding_provider(self.provider_name),
        )

    def build_embeddings(self, chunks: list[PersistedChunk]) -> list[PersistedEmbedding]:
        """Generate deterministic embeddings for persisted chunks."""

        return [
            PersistedEmbedding(
                chunk_id=chunk.id,
                provider=self.provider_name,
                model=self.model_name,
                content_hash=chunk_content_hash(chunk.text),
                vector=self._provider.embed(chunk.text, model=self.model_name),
            )
            for chunk in chunks
        ]

    def embed_query(self, query: str) -> list[float]:
        """Return cached query embedding for active provider/model."""

        cache_key = (self.provider_name, self.model_name, query)
        cached = self._query_cache.get(cache_key)
        if cached is not None:
            self._query_cache.move_to_end(cache_key)
            return list(cached)

        vector = self._provider.embed(query, model=self.model_name)
        self._query_cache[cache_key] = list(vector)
        self._query_cache.move_to_end(cache_key)
        while len(self._query_cache) > self.query_cache_size:
            self._query_cache.popitem(last=False)
        return list(vector)


def _load_fastembed_model(model_name: str):
    with _FASTEMBED_MODEL_LOCK:
        cached = _FASTEMBED_MODELS.get(model_name)
        if cached is not None:
            return cached
        try:
            from fastembed import TextEmbedding
        except ImportError as exc:  # pragma: no cover - dependency install issue
            raise RuntimeError("fastembed is not installed") from exc
        model = TextEmbedding(model_name=model_name)
        _FASTEMBED_MODELS[model_name] = model
        return model
