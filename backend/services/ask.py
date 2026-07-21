from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from uuid import uuid4

from fastapi import Request

from backend.db import connect_sqlite
from backend.errors import request_id_for, sse_error_payload
from backend.indexer.workspace_manager import workspace_manager
from backend.indexer.vectors import get_retrieval_provider
from backend.models import (
    ArtifactEvent,
    AskRequest,
    CitationsEvent,
    CitationChip,
    ConceptsEvent,
    DoneEvent,
    IntentEvent,
    StepEvent,
    TokenEvent,
)
from backend.sandbox.runner import run_generated_analysis
from backend.storage import (
    create_artifact,
    load_dataset_profiles,
    load_workspace_counts,
    upsert_concept_updates,
    validate_citation_anchors,
)
from backend.telemetry.tracing import request_metrics_tracker

from .retrieval import load_fallback_retrieval, source_label


async def stream_ask_events(
    request: AskRequest,
    http_request: Request,
    get_llm_client: Callable[[], object],
    sse: Callable[[dict], str],
) -> AsyncIterator[str]:
    answer_id = f"answer_{uuid4()}"
    request_id = request_id_for(http_request)
    request_metrics = request_metrics_tracker.begin("/ask")
    try:
        workspace_record = workspace_manager.get(request.workspace_id)
        if workspace_record is None:
            raise ValueError(f"Unknown workspace_id: {request.workspace_id}")

        client = get_llm_client()
        intent_result = await asyncio.to_thread(client.classify_intent, request.question)
        yield sse(
            IntentEvent(
                event="intent",
                answer_id=answer_id,
                intent=intent_result.intent,
                targets=intent_result.targets,
                connect=intent_result.connect,
            ).model_dump()
        )

        yield sse(
            StepEvent(
                event="step",
                answer_id=answer_id,
                step="retrieval",
                label="searching selected workspace",
                status="started",
            ).model_dump()
        )

        connection = connect_sqlite(workspace_record.db_path)
        try:
            _file_count, workspace_chunk_count = load_workspace_counts(connection)
            retrieval_provider = get_retrieval_provider(connection)
            if hasattr(client, "build_plan") and hasattr(client, "execute_plan"):
                execution_plan = await asyncio.to_thread(
                    client.build_plan,
                    request.question,
                    intent_result,
                )
                execution_context_data = await asyncio.to_thread(
                    client.execute_plan,
                    plan=execution_plan,
                    question=request.question,
                    workspace_root=workspace_record.root,
                    artifacts_dir=workspace_record.artifacts_dir,
                    db_path=workspace_record.db_path,
                    answer_id=answer_id,
                    retrieval_provider=retrieval_provider,
                )
                matched_retrieval_results = execution_context_data.retrieved_chunks
            else:
                execution_plan = None
                execution_context_data = None
                matched_retrieval_results = client.resolve_retrieval(request.question, retrieval_provider)
            retrieval_results = list(matched_retrieval_results)
            if not retrieval_results and workspace_chunk_count > 0:
                retrieval_results = load_fallback_retrieval(connection, limit=5)
        finally:
            connection.close()

        workspace_has_searchable_content = workspace_chunk_count > 0

        yield sse(
            StepEvent(
                event="step",
                answer_id=answer_id,
                step="retrieval",
                label=(
                    f"retrieved {len(matched_retrieval_results)} passages"
                    if matched_retrieval_results
                    else "workspace contains no searchable passages"
                    if not workspace_has_searchable_content
                    else "no supporting passages matched this question"
                ),
                status="ok" if matched_retrieval_results else "no_match",
            ).model_dump()
        )

        yield sse(
            StepEvent(
                event="step",
                answer_id=answer_id,
                step="grounding",
                label="grounding answer in retrieved passages",
                status="started",
            ).model_dump()
        )

        execution_context = None
        code_chip: CitationChip | None = None
        emitted_artifacts: list[ArtifactEvent] = []
        should_run_analysis = intent_result.intent in {"analyze", "visualize", "connect"}
        if execution_context_data is not None:
            execution_context = execution_context_data.intermediate_results.get("answer_context")
            connection = connect_sqlite(workspace_record.db_path)
            try:
                for draft in execution_context_data.generated_artifacts:
                    artifact_card = create_artifact(
                        connection,
                        workspace_record.artifacts_dir,
                        kind=draft.persisted_kind,
                        title=draft.title,
                        answer_id=answer_id,
                        payload_text=draft.payload_text,
                        file_contents=draft.payload_text if draft.file_extension else None,
                        file_extension=draft.file_extension,
                        existing_file_path=draft.existing_file_path,
                    )
                    if draft.persisted_kind == "script":
                        code_chip = CitationChip(
                            chip_type="code",
                            label=f"{Path(artifact_card.url or '').name or artifact_card.title} output",
                            artifact_id=artifact_card.id,
                        )
                    if draft.emit_event_kind is not None:
                        emitted_artifacts.append(
                            ArtifactEvent(
                                event="artifact",
                                answer_id=answer_id,
                                artifact_id=artifact_card.id,
                                kind=draft.emit_event_kind,
                                title=artifact_card.title,
                                url=artifact_card.url,
                            )
                        )
                connection.commit()
            finally:
                connection.close()
            for emitted_artifact in emitted_artifacts:
                yield sse(emitted_artifact.model_dump())
            emitted_artifacts.clear()
            if any(step.step_type == "execute_python" for step in execution_context_data.step_executions):
                yield sse(
                    StepEvent(
                        event="step",
                        answer_id=answer_id,
                        step="codegen",
                        label="generated local execution plan",
                        status="ok",
                    ).model_dump()
                )
                execution_step = next(
                    (
                        step
                        for step in execution_context_data.step_executions
                        if step.step_type == "execute_python"
                    ),
                    None,
                )
                yield sse(
                    StepEvent(
                        event="step",
                        answer_id=answer_id,
                        step="execution",
                        label="analysis completed locally"
                        if execution_step and execution_step.status == "ok"
                        else "analysis execution failed",
                        status="ok" if execution_step and execution_step.status == "ok" else "failed",
                    ).model_dump()
                )
        elif should_run_analysis:
            connection = connect_sqlite(workspace_record.db_path)
            try:
                dataset_profiles = load_dataset_profiles(connection)
            finally:
                connection.close()

            if dataset_profiles:
                yield sse(
                    StepEvent(
                        event="step",
                        answer_id=answer_id,
                        step="codegen",
                        label="generating local analysis script",
                        status="started",
                    ).model_dump()
                )
                analysis_plan = await asyncio.to_thread(
                    client.generate_analysis_script,
                    question=request.question,
                    retrieval_results=retrieval_results,
                    dataset_profiles_json=json.dumps(
                        [profile.model_dump() for profile in dataset_profiles]
                    ),
                )
                yield sse(
                    StepEvent(
                        event="step",
                        answer_id=answer_id,
                        step="codegen",
                        label=f"wrote analysis for {analysis_plan.target_file_path}",
                        status="ok",
                    ).model_dump()
                )
                yield sse(
                    StepEvent(
                        event="step",
                        answer_id=answer_id,
                        step="execution",
                        label="running local analysis sandbox",
                        status="started",
                    ).model_dump()
                )
                sandbox_result = await asyncio.to_thread(
                    run_generated_analysis,
                    workspace_root=workspace_record.root,
                    artifacts_dir=workspace_record.artifacts_dir,
                    answer_id=answer_id,
                    script_source=analysis_plan.script,
                )
                yield sse(
                    StepEvent(
                        event="step",
                        answer_id=answer_id,
                        step="execution",
                        label="analysis completed locally",
                        status="ok",
                    ).model_dump()
                )

                connection = connect_sqlite(workspace_record.db_path)
                try:
                    script_artifact = create_artifact(
                        connection,
                        workspace_record.artifacts_dir,
                        kind="script",
                        title=analysis_plan.title,
                        answer_id=answer_id,
                        payload_text=sandbox_result.stdout or None,
                        existing_file_path=sandbox_result.script_path,
                    )
                    code_chip = CitationChip(
                        chip_type="code",
                        label=f"{sandbox_result.script_path.name} output",
                        artifact_id=script_artifact.id,
                    )
                    emitted_artifacts.append(
                        ArtifactEvent(
                            event="artifact",
                            answer_id=answer_id,
                            artifact_id=script_artifact.id,
                            kind="script",
                            title=script_artifact.title,
                            url=script_artifact.url,
                        )
                    )
                    if sandbox_result.chart_path.exists():
                        chart_artifact = create_artifact(
                            connection,
                            workspace_record.artifacts_dir,
                            kind="chart",
                            title=f"{analysis_plan.title} chart",
                            answer_id=answer_id,
                            existing_file_path=sandbox_result.chart_path,
                        )
                        emitted_artifacts.append(
                            ArtifactEvent(
                                event="artifact",
                                answer_id=answer_id,
                                artifact_id=chart_artifact.id,
                                kind="chart",
                                title=chart_artifact.title,
                                url=chart_artifact.url,
                            )
                        )
                    connection.commit()
                finally:
                    connection.close()
                for emitted_artifact in emitted_artifacts:
                    yield sse(emitted_artifact.model_dump())
                emitted_artifacts.clear()
                execution_context = json.dumps(
                    {
                        "target_file_path": analysis_plan.target_file_path,
                        "stdout": sandbox_result.stdout,
                        "stderr": sandbox_result.stderr,
                        "result": sandbox_result.result_payload,
                    }
                )

        answer_chunks: list[str] = []
        for delta in client.stream_grounded_answer(
            request.question,
            intent_result.intent,
            retrieval_results,
            execution_context=execution_context,
        ):
            if delta:
                request_metrics.observe_chunk(delta)
                answer_chunks.append(delta)
                yield sse(
                    TokenEvent(
                        event="token",
                        answer_id=answer_id,
                        text=delta,
                    ).model_dump()
                )

        yield sse(
            StepEvent(
                event="step",
                answer_id=answer_id,
                step="grounding",
                label=(
                    "answer grounded"
                    if matched_retrieval_results
                    else "workspace has no indexed content"
                    if not workspace_has_searchable_content
                    else "no supporting sources found"
                ),
                status="ok" if matched_retrieval_results else "no_match",
            ).model_dump()
        )

        raw_chips = [
            CitationChip(
                chip_type="document",
                label=source_label(result.relative_path, result.anchor),
                anchor=f"{result.file_id}#{result.anchor}",
            )
            for result in matched_retrieval_results
        ]
        if code_chip is not None:
            raw_chips.append(code_chip)

        concepts = (
            client.extract_concepts(request.question, matched_retrieval_results)
            if matched_retrieval_results
            else []
        )
        artifact_event = ArtifactEvent(
            event="artifact",
            answer_id=answer_id,
            artifact_id="",
            kind="explainer",
            title="",
            url=None,
        )
        answer_text = "".join(answer_chunks).strip()

        connection = connect_sqlite(workspace_record.db_path)
        try:
            valid_chips = validate_citation_anchors(connection, raw_chips)
            if answer_text:
                artifact_card = create_artifact(
                    connection,
                    workspace_record.artifacts_dir,
                    kind="explainer",
                    title=f"Answer: {request.question[:60]}",
                    answer_id=answer_id,
                    payload_text=answer_text,
                    file_contents=answer_text,
                    file_extension="txt",
                )
                artifact_event = ArtifactEvent(
                    event="artifact",
                    answer_id=answer_id,
                    artifact_id=artifact_card.id,
                    kind="explainer",
                    title=artifact_card.title,
                    url=artifact_card.url,
                )
            upsert_concept_updates(
                connection,
                concepts,
                source_anchor=valid_chips[0].anchor if valid_chips else None,
            )
            connection.commit()
        finally:
            connection.close()

        yield sse(artifact_event.model_dump())
        yield sse(
            CitationsEvent(
                event="citations",
                answer_id=answer_id,
                chips=valid_chips,
            ).model_dump()
        )
        if concepts:
            yield sse(
                ConceptsEvent(
                    event="concepts",
                    answer_id=answer_id,
                    updates=concepts,
                ).model_dump()
            )
        yield sse(DoneEvent(event="done", answer_id=answer_id).model_dump())
        request_metrics.complete()
    except Exception as exc:
        request_metrics.complete()
        yield sse(
            sse_error_payload(
                exc=exc,
                request_id=request_id,
                answer_id=answer_id,
                context={"route": "/ask", "workspace_id": request.workspace_id},
            )
        )
