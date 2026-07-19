"""Indexing orchestration for discovery, parsing, chunking, and persistence."""

from __future__ import annotations

import time
from pathlib import Path

from backend.db import connect_sqlite
from backend.indexer.chunking import build_chunks
from backend.indexer.embeddings import EmbeddingService
from backend.indexer.discovery import discover_files
from backend.indexer.events import EventStreamHub
from backend.indexer.parsers import PARSER_REGISTRY, DiscoveredFile, ParsedFile
from backend.indexer.workspace import initialize_workspace
from backend.models import (
    BriefReadyEvent,
    DatasetProfile,
    FileParsedEvent,
    FileStartedEvent,
    IndexCompleteEvent,
    StarterCard,
    WorkspaceBrief,
)
from backend.storage import (
    file_id_for_path,
    indexing_transaction,
    persist_indexing_result,
    select_chunks_requiring_embeddings,
    upsert_embeddings,
    upsert_workspace_meta,
    utc_now_iso,
)
from backend.telemetry.tracing import metrics_registry, trace_collector


def parse_file(file: DiscoveredFile) -> ParsedFile:
    """Parse one discovered file into normalized raw representation."""

    parser = PARSER_REGISTRY.get(file.kind)
    if parser is None:
        return ParsedFile(
            path=file.path,
            relative_path=file.relative_path,
            display_name=file.display_name,
            size_bytes=file.size_bytes,
            kind=file.kind,
            parse_status="skipped",
            content=None,
            error_message=None,
        )

    try:
        content = parser(file)
    except Exception as exc:
        return ParsedFile(
            path=file.path,
            relative_path=file.relative_path,
            display_name=file.display_name,
            size_bytes=file.size_bytes,
            kind=file.kind,
            parse_status="failed",
            content=None,
            error_message=str(exc),
        )

    return ParsedFile(
        path=file.path,
        relative_path=file.relative_path,
        display_name=file.display_name,
        size_bytes=file.size_bytes,
        kind=file.kind,
        parse_status="parsed",
        content=content,
        error_message=None,
    )


def discover_and_parse(workspace_root: Path) -> list[ParsedFile]:
    """Run recursive discovery and parse each supported file."""

    return [parse_file(file) for file in discover_files(workspace_root)]


def run_indexing(workspace_root: Path, workspace_id: str, event_hub: EventStreamHub) -> None:
    """Execute Phase 1 indexing pipeline and publish SSE progress events."""

    indexing_started = time.perf_counter()
    workspace_paths = initialize_workspace(workspace_root)
    discovered_files = discover_files(workspace_root)
    chunk_count = 0
    embedding_service = EmbeddingService()

    connection = connect_sqlite(workspace_paths.db_path)
    try:
        with trace_collector.span("indexing", workspace_id=workspace_id, file_count=len(discovered_files)):
            with indexing_transaction(connection):
                upsert_workspace_meta(connection, "indexed_at", utc_now_iso())
                upsert_workspace_meta(connection, "course_title", workspace_root.name)
                upsert_workspace_meta(connection, "workspace_id", workspace_id)

                for discovered_file in discovered_files:
                    event_hub.publish(
                        FileStartedEvent(
                            event="file_started",
                            file_id=file_id_for_path(discovered_file.relative_path),
                            display_name=discovered_file.display_name,
                        ).model_dump()
                    )

                    parse_started = time.perf_counter()
                    parsed_file = parse_file(discovered_file)
                    metrics_registry.record("parsing_duration_ms", (time.perf_counter() - parse_started) * 1000)
                    chunk_started = time.perf_counter()
                    chunks = build_chunks(parsed_file)
                    metrics_registry.record("chunking_duration_ms", (time.perf_counter() - chunk_started) * 1000)
                    file_id, persisted_chunks = persist_indexing_result(connection, parsed_file, chunks)
                    chunk_count += len(chunks)
                    embed_started = time.perf_counter()
                    embedding_warning = _persist_embeddings(
                        connection,
                        embedding_service,
                        persisted_chunks,
                    )
                    metrics_registry.record("embedding_duration_ms", (time.perf_counter() - embed_started) * 1000)

                    event_hub.publish(
                        FileParsedEvent(
                            event="file_parsed",
                            file_id=file_id,
                            display_name=parsed_file.display_name,
                            parse_status=parsed_file.parse_status,
                            parse_summary=_build_parse_summary(
                                parsed_file,
                                len(chunks),
                                embedding_warning=embedding_warning,
                            ),
                        ).model_dump()
                    )

                event_hub.publish(
                    IndexCompleteEvent(
                        event="index_complete",
                        file_count=len(discovered_files),
                        chunk_count=chunk_count,
                    ).model_dump()
                )

                brief = build_workspace_brief(workspace_root, discovered_files, connection)
                upsert_workspace_meta(connection, "brief_json", brief.model_dump_json())
                event_hub.publish(
                    BriefReadyEvent(event="brief_ready", brief=brief).model_dump()
                )
    finally:
        connection.close()
        event_hub.close()
        metrics_registry.record("indexing_duration_ms", (time.perf_counter() - indexing_started) * 1000)


def build_workspace_brief(
    workspace_root: Path,
    discovered_files: list[DiscoveredFile],
    connection,
) -> WorkspaceBrief:
    """Build contract-valid local brief from indexed content."""

    starters: list[StarterCard] = []
    dataset_profiles = _load_profiles(connection)
    anomaly_starter = _build_anomaly_starter(dataset_profiles)
    if anomaly_starter is not None:
        starters.append(anomaly_starter)

    for file in discovered_files:
        if len(starters) >= 4:
            break
        starters.append(
            StarterCard(
                text=f"Open {file.display_name}",
                file_path=file.relative_path,
                seed="concept",
            )
        )

    while len(starters) < 3:
        starters.append(
            StarterCard(
                text=f"Explore {workspace_root.name}",
                file_path=discovered_files[0].relative_path if discovered_files else "",
                seed="practice" if len(starters) == 2 else "concept",
            )
        )

    kinds: dict[str, int] = {}
    for file in discovered_files:
        kinds[file.kind] = kinds.get(file.kind, 0) + 1
    summary_parts = [f"{count} {kind}" for kind, count in sorted(kinds.items())]
    summary = f"Indexed {len(discovered_files)} files"
    if summary_parts:
        summary += f": {', '.join(summary_parts)}."
    if anomaly_starter is not None:
        summary += " Found dataset anomaly starter from outlier flags."

    return WorkspaceBrief(
        course_title=workspace_root.name,
        summary=summary,
        starter_cards=starters[:4],
    )


def _persist_embeddings(
    connection,
    embedding_service: EmbeddingService,
    persisted_chunks,
) -> str | None:
    if not persisted_chunks:
        return None

    try:
        stale_chunks = select_chunks_requiring_embeddings(
            connection,
            persisted_chunks,
            provider=embedding_service.provider_name,
            model=embedding_service.model_name,
        )
        if not stale_chunks:
            return None
        embeddings = embedding_service.build_embeddings(stale_chunks)
        upsert_embeddings(connection, embeddings)
    except Exception as exc:
        return f"embedding warning: {exc}"
    return None


def _build_parse_summary(
    parsed_file: ParsedFile,
    chunk_count: int,
    embedding_warning: str | None = None,
) -> str:
    if parsed_file.content and parsed_file.content.dataset_profile is not None:
        profile = parsed_file.content.dataset_profile
        summary = f"parsed {parsed_file.display_name} - {profile.row_count} rows, {len(profile.columns)} columns"
        return _append_embedding_warning(summary, embedding_warning)
    if parsed_file.parse_status == "parsed":
        summary = f"parsed {parsed_file.display_name} - {chunk_count} chunks"
        return _append_embedding_warning(summary, embedding_warning)
    if parsed_file.error_message:
        return parsed_file.error_message
    return f"{parsed_file.parse_status} {parsed_file.display_name}"


def _append_embedding_warning(summary: str, embedding_warning: str | None) -> str:
    if not embedding_warning:
        return summary
    return f"{summary} ({embedding_warning})"


def _load_profiles(connection) -> list[DatasetProfile]:
    rows = connection.execute("SELECT profile_json FROM dataset_profiles").fetchall()
    return [DatasetProfile.model_validate_json(str(row["profile_json"])) for row in rows]


def _build_anomaly_starter(dataset_profiles: list[DatasetProfile]) -> StarterCard | None:
    for profile in dataset_profiles:
        for column in profile.columns:
            for flag in column.outlier_flags or []:
                return StarterCard(
                    text=f"{profile.file_path}: investigate {flag.group} on {flag.metric}",
                    file_path=profile.file_path,
                    seed="anomaly",
                )
    return None
