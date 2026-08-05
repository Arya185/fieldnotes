from __future__ import annotations

import math
from collections import defaultdict
from typing import List, Dict, Any

from backend.indexer.embeddings import EmbeddingService
from backend.indexer.vectors import cosine_similarity
from backend.indexer.bm25 import RetrievalChunk


def _normalize_scores(results: List[RetrievalChunk]) -> Dict[tuple[str, str], float]:
    scores = {(r.file_id, r.anchor): float(getattr(r, "score", 0.0) or 0.0) for r in results}
    if not scores:
        return {}
    mn = min(scores.values())
    mx = max(scores.values())
    if mx == mn:
        return {k: (1.0 if v > 0 else 0.0) for k, v in scores.items()}
    return {k: (v - mn) / (mx - mn) for k, v in scores.items()}


def _vec_cosine(a: List[float], b: List[float]) -> float:
    # fallback to math-based cosine if needed
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def organize_retrieval_results(
    retrieval_results: List[RetrievalChunk],
    *,
    embedding_service: EmbeddingService | None = None,
    dedup_threshold: float = 0.95,
    cluster_threshold: float = 0.72,
) -> Dict[str, Any]:
    """Organize flat retrieval results into grouped, clustered, and de-duplicated evidence.

    Returns a dict with keys: clusters (list), conflicts (list).
    Each cluster contains members with document, anchor, text, and confidence.
    """
    if embedding_service is None:
        embedding_service = EmbeddingService()

    # Normalize confidence scores
    normalized = _normalize_scores(retrieval_results)

    # Build unique items and embeddings
    items: list[dict[str, Any]] = []
    seen = []
    for r in retrieval_results:
        key = (r.file_id, r.anchor)
        # dedup by exact key
        if key in {(s["file_id"], s["anchor"]) for s in seen}:
            continue
        seen.append({"file_id": r.file_id, "anchor": r.anchor})
        text = r.chunk.strip()
        vec = embedding_service.embed_query(text)  # uses query cache; good enough for clustering
        conf = normalized.get((r.file_id, r.anchor), 0.0)
        items.append({"file_id": r.file_id, "relative_path": r.relative_path, "anchor": r.anchor, "text": text, "vec": vec, "confidence": conf})

    # Merge near-duplicates first
    unique_items: List[dict[str, Any]] = []
    for item in items:
        merged = False
        for u in unique_items:
            sim = _vec_cosine(item["vec"], u["vec"]) if item["vec"] and u["vec"] else 0.0
            if sim >= dedup_threshold:
                # merge citations
                u.setdefault("citations", []).append({"file_id": item["file_id"], "anchor": item["anchor"], "relative_path": item["relative_path"], "confidence": item["confidence"]})
                # keep longer text as representative
                if len(item["text"]) > len(u["text"]):
                    u["text"] = item["text"]
                u["confidence"] = max(u.get("confidence", 0.0), item["confidence"])
                merged = True
                break
        if not merged:
            entry = dict(item)
            entry["citations"] = [{"file_id": item["file_id"], "anchor": item["anchor"], "relative_path": item["relative_path"], "confidence": item["confidence"]}]
            unique_items.append(entry)

    # Cluster by semantic similarity
    clusters: list[list[dict[str, Any]]] = []
    centroids: list[list[float]] = []
    for item in unique_items:
        placed = False
        for idx, centroid in enumerate(centroids):
            sim = _vec_cosine(item["vec"], centroid) if item["vec"] and centroid else 0.0
            if sim >= cluster_threshold:
                clusters[idx].append(item)
                # update centroid (mean)
                n = len(clusters[idx])
                centroids[idx] = [((centroid[i] * (n - 1)) + item["vec"][i]) / n for i in range(len(item["vec"]))]
                placed = True
                break
        if not placed:
            clusters.append([item])
            centroids.append(list(item["vec"]))

    # Build cluster summaries and metadata
    built_clusters = []
    for cid, members in enumerate(clusters, start=1):
        # representative text = longest member text
        rep = max(members, key=lambda m: len(m["text"]))
        citations = []
        for m in members:
            for c in m.get("citations", []):
                citations.append({"document": c["relative_path"], "file_id": c["file_id"], "anchor": c["anchor"], "confidence": c["confidence"]})
        built_clusters.append({
            "cluster_id": f"c{cid}",
            "representative": rep["text"],
            "members": members,
            "citations": citations,
            "confidence": max(m.get("confidence", 0.0) for m in members) if members else 0.0,
        })

    # Simple conflict detection: if two clusters share token overlap but differ in negation presence
    negation_words = {"not", "no", "never", "without", "none", "cannot", "can't", "doesn't", "didn't", "isn't", "wasn't"}
    conflicts = []
    for i in range(len(built_clusters)):
        for j in range(i + 1, len(built_clusters)):
            a = built_clusters[i]["representative"].lower().split()
            b = built_clusters[j]["representative"].lower().split()
            common = set(a) & set(b)
            if len(common) >= 3:
                a_neg = any(tok in negation_words for tok in a)
                b_neg = any(tok in negation_words for tok in b)
                if a_neg != b_neg:
                    conflicts.append({"cluster_a": built_clusters[i]["cluster_id"], "cluster_b": built_clusters[j]["cluster_id"], "shared_terms": list(common)})

    return {"clusters": built_clusters, "conflicts": conflicts}
