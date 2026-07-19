"""Offline retrieval evaluation helpers."""

from __future__ import annotations

from dataclasses import dataclass

from backend.indexer.bm25 import RetrievalProvider
from backend.indexer.reranker import Reranker


@dataclass(frozen=True)
class RetrievalBenchmark:
    query: str
    relevant_anchors: set[str]
    relevance_by_anchor: dict[str, int] | None = None


@dataclass(frozen=True)
class RetrievalMetrics:
    recall_at_5: float
    recall_at_10: float
    mrr: float
    ndcg_at_5: float
    ndcg_at_10: float


@dataclass(frozen=True)
class RetrievalComparison:
    before: RetrievalMetrics
    after: RetrievalMetrics


@dataclass(frozen=True)
class ExecutionEvaluationCase:
    completed: bool
    succeeded: bool
    citations_preserved: bool
    analysis_correct: bool


@dataclass(frozen=True)
class ExecutionEvaluationMetrics:
    execution_success_rate: float
    plan_completion_rate: float
    analysis_correctness: float
    citation_preservation_rate: float


def evaluate_benchmarks(
    retrieval_provider: RetrievalProvider,
    benchmarks: list[RetrievalBenchmark],
    *,
    reranker: Reranker | None = None,
    candidate_limit: int = 10,
) -> RetrievalMetrics:
    """Compute Recall@5, Recall@10, MRR, nDCG@5, nDCG@10."""

    if not benchmarks:
        return RetrievalMetrics(
            recall_at_5=0.0,
            recall_at_10=0.0,
            mrr=0.0,
            ndcg_at_5=0.0,
            ndcg_at_10=0.0,
        )

    recall5_hits = 0
    recall10_hits = 0
    reciprocal_ranks = 0.0
    ndcg5_total = 0.0
    ndcg10_total = 0.0

    for benchmark in benchmarks:
        candidates = retrieval_provider.search(benchmark.query, limit=max(10, candidate_limit))
        ranked_results = (
            reranker.rerank(benchmark.query, candidates, limit=10).selected_chunks
            if reranker is not None
            else candidates[:10]
        )
        top5 = ranked_results[:5]
        top10 = ranked_results[:10]

        anchors5 = {f"{row.file_id}#{row.anchor}" for row in top5}
        anchors10 = {f"{row.file_id}#{row.anchor}" for row in top10}
        if anchors5 & benchmark.relevant_anchors:
            recall5_hits += 1
        if anchors10 & benchmark.relevant_anchors:
            recall10_hits += 1

        reciprocal_ranks += reciprocal_rank(top10, benchmark.relevant_anchors)
        ndcg5_total += ndcg(top5, benchmark)
        ndcg10_total += ndcg(top10, benchmark)

    total = len(benchmarks)
    return RetrievalMetrics(
        recall_at_5=recall5_hits / total,
        recall_at_10=recall10_hits / total,
        mrr=reciprocal_ranks / total,
        ndcg_at_5=ndcg5_total / total,
        ndcg_at_10=ndcg10_total / total,
    )


def compare_reranking(
    retrieval_provider: RetrievalProvider,
    reranker: Reranker,
    benchmarks: list[RetrievalBenchmark],
    *,
    candidate_limit: int = 10,
) -> RetrievalComparison:
    """Compare metrics before and after reranking."""

    return RetrievalComparison(
        before=evaluate_benchmarks(
            retrieval_provider,
            benchmarks,
            candidate_limit=candidate_limit,
        ),
        after=evaluate_benchmarks(
            retrieval_provider,
            benchmarks,
            reranker=reranker,
            candidate_limit=candidate_limit,
        ),
    )


def evaluate_execution_cases(cases: list[ExecutionEvaluationCase]) -> ExecutionEvaluationMetrics:
    """Compute execution/planning quality metrics from fixture cases."""

    if not cases:
        return ExecutionEvaluationMetrics(
            execution_success_rate=0.0,
            plan_completion_rate=0.0,
            analysis_correctness=0.0,
            citation_preservation_rate=0.0,
        )

    total = len(cases)
    return ExecutionEvaluationMetrics(
        execution_success_rate=sum(1 for case in cases if case.succeeded) / total,
        plan_completion_rate=sum(1 for case in cases if case.completed) / total,
        analysis_correctness=sum(1 for case in cases if case.analysis_correct) / total,
        citation_preservation_rate=sum(1 for case in cases if case.citations_preserved) / total,
    )


def reciprocal_rank(results, relevant_anchors: set[str]) -> float:
    """Return reciprocal rank for first relevant result."""

    for index, row in enumerate(results, start=1):
        if f"{row.file_id}#{row.anchor}" in relevant_anchors:
            return 1.0 / index
    return 0.0


def ndcg(results, benchmark: RetrievalBenchmark) -> float:
    """Compute normalized discounted cumulative gain."""

    relevance_by_anchor = (
        benchmark.relevance_by_anchor
        if benchmark.relevance_by_anchor is not None
        else {anchor: 1 for anchor in benchmark.relevant_anchors}
    )
    dcg = 0.0
    for index, row in enumerate(results, start=1):
        relevance = relevance_by_anchor.get(f"{row.file_id}#{row.anchor}", 0)
        if relevance > 0:
            dcg += (2**relevance - 1) / _log2(index + 1)

    ideal_relevances = sorted(relevance_by_anchor.values(), reverse=True)[: len(results)]
    ideal_dcg = 0.0
    for index, relevance in enumerate(ideal_relevances, start=1):
        ideal_dcg += (2**relevance - 1) / _log2(index + 1)
    if ideal_dcg == 0:
        return 0.0
    return dcg / ideal_dcg


def _log2(value: int) -> float:
    import math

    return math.log2(value)
