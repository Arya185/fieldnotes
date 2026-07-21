"""Internal tracing, metrics, and inspection helpers."""

from __future__ import annotations

import json
import re
import time
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator, Literal
from uuid import uuid4

from backend.config import ENABLE_METRICS, ENABLE_TRACING, VERBOSE_TRACING, parse_env_flag

try:
    import resource
except ModuleNotFoundError:  # pragma: no cover - Windows
    resource = None


SpanStatus = Literal["ok", "failed"]
SpanType = Literal[
    "planning",
    "retrieval",
    "reranking",
    "execution",
    "sandbox",
    "artifact_persistence",
    "responses_api",
    "indexing",
    "parsing",
    "chunking",
    "embedding",
]


@dataclass(frozen=True)
class TraceSpan:
    span_type: SpanType
    trace_id: str
    start_time: str
    end_time: str
    duration_ms: int
    status: SpanStatus
    error: str | None
    metadata: dict[str, Any]


@dataclass
class TraceCollector:
    enabled: bool = field(default_factory=lambda: parse_env_flag(ENABLE_TRACING))
    verbose: bool = field(default_factory=lambda: parse_env_flag(VERBOSE_TRACING))
    trace_id: str = field(default_factory=lambda: f"trace_{uuid4()}")
    spans: list[TraceSpan] = field(default_factory=list)

    @contextmanager
    def span(self, span_type: SpanType, **metadata: Any) -> Iterator[dict[str, Any]]:
        if not self.enabled:
            yield metadata
            return
        started = time.perf_counter()
        start_time = utc_now_iso()
        payload = dict(metadata)
        status: SpanStatus = "ok"
        error: str | None = None
        try:
            yield payload
        except Exception as exc:
            status = "failed"
            error = str(exc)
            raise
        finally:
            self.spans.append(
                TraceSpan(
                    span_type=span_type,
                    trace_id=self.trace_id,
                    start_time=start_time,
                    end_time=utc_now_iso(),
                    duration_ms=int((time.perf_counter() - started) * 1000),
                    status=status,
                    error=error,
                    metadata=payload if self.verbose or status == "failed" else _compact_metadata(payload),
                )
            )

    def snapshot(self) -> list[TraceSpan]:
        return list(self.spans)


@dataclass
class MetricsRegistry:
    enabled: bool = field(default_factory=lambda: parse_env_flag(ENABLE_METRICS))
    values: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))

    def record(self, name: str, value: float) -> None:
        if not self.enabled:
            return
        self.values[name].append(float(value))

    def snapshot(self) -> dict[str, dict[str, float]]:
        result: dict[str, dict[str, float]] = {}
        for name, entries in self.values.items():
            if not entries:
                continue
            result[name] = {
                "count": float(len(entries)),
                "min": min(entries),
                "max": max(entries),
                "avg": sum(entries) / len(entries),
            }
        return result


@dataclass(frozen=True)
class RequestMetricsSnapshot:
    endpoint: str
    started_at: str
    first_token_at: str | None
    completed_at: str | None
    ttft_ms: float | None
    latency_ms: float | None
    chunk_count: int
    token_count_estimate: int
    tokens_per_second: float | None
    memory_rss_mb: float | None
    gpu: str


@dataclass
class RequestMetricsTracker:
    last_request: RequestMetricsSnapshot | None = None

    def begin(self, endpoint: str) -> "RequestMetricsSession":
        return RequestMetricsSession(tracker=self, endpoint=endpoint)


@dataclass
class RequestMetricsSession:
    tracker: RequestMetricsTracker
    endpoint: str
    started_at: str = field(default_factory=lambda: utc_now_iso())
    started_perf: float = field(default_factory=time.perf_counter)
    first_token_perf: float | None = None
    first_token_at: str | None = None
    chunk_count: int = 0
    token_count_estimate: int = 0

    def observe_chunk(self, text: str) -> None:
        if self.first_token_perf is None:
            self.first_token_perf = time.perf_counter()
            self.first_token_at = utc_now_iso()
        self.chunk_count += 1
        self.token_count_estimate += len(re.findall(r"\S+", text))

    def complete(self) -> None:
        finished_perf = time.perf_counter()
        latency_ms = (finished_perf - self.started_perf) * 1000
        ttft_ms = None
        if self.first_token_perf is not None:
            ttft_ms = (self.first_token_perf - self.started_perf) * 1000
        tokens_per_second = None
        if self.first_token_perf is not None and self.token_count_estimate > 0:
            generation_seconds = max(finished_perf - self.first_token_perf, 1e-6)
            tokens_per_second = self.token_count_estimate / generation_seconds
        self.tracker.last_request = RequestMetricsSnapshot(
            endpoint=self.endpoint,
            started_at=self.started_at,
            first_token_at=self.first_token_at,
            completed_at=utc_now_iso(),
            ttft_ms=ttft_ms,
            latency_ms=latency_ms,
            chunk_count=self.chunk_count,
            token_count_estimate=self.token_count_estimate,
            tokens_per_second=tokens_per_second,
            memory_rss_mb=_memory_rss_mb(),
            gpu="unavailable",
        )


def _memory_rss_mb() -> float | None:
    if resource is None:
        return None
    try:
        usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    except Exception:
        return None
    if usage <= 0:
        return None
    # macOS reports bytes, Linux kilobytes.
    return usage / (1024 * 1024) if usage > 10_000_000 else usage / 1024


@dataclass(frozen=True)
class LogContext:
    workspace_id: str | None = None
    run_id: str | None = None
    request_id: str | None = None
    trace_id: str | None = None


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def structured_log(
    *,
    component: str,
    severity: str,
    message: str,
    context: LogContext,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Build structured JSON log line."""

    payload = {
        "workspace_id": context.workspace_id,
        "run_id": context.run_id,
        "request_id": context.request_id,
        "trace_id": context.trace_id,
        "component": component,
        "severity": severity,
        "timestamp": utc_now_iso(),
        "message": message,
        "metadata": metadata or {},
    }
    return json.dumps(payload, sort_keys=True)


def save_benchmark_results(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def load_benchmark_results(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _compact_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key, value in metadata.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            compact[key] = value
        elif isinstance(value, list):
            compact[key] = f"list[{len(value)}]"
        elif isinstance(value, dict):
            compact[key] = f"dict[{len(value)}]"
        else:
            compact[key] = str(type(value).__name__)
    return compact


trace_collector = TraceCollector()
metrics_registry = MetricsRegistry()
request_metrics_tracker = RequestMetricsTracker()
