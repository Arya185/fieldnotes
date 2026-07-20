"""Backend entrypoint for Phase 1 indexing, ask, quiz, and artifact APIs."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import os
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from backend.agent.llm import LLMClient
from backend.config import FIELDNOTES_VERSION, ConfigurationError, determine_llm_mode, validate_runtime_configuration
from backend.db import connect_sqlite, latest_storage_warning_message
from backend.errors import error_response, request_id_for, sse_error_payload
from backend.indexer.bm25 import RetrievalChunk
from backend.indexer.events import run_manager
from backend.indexer.pipeline import run_indexing
from backend.indexer.workspace_manager import workspace_manager
from backend.indexer.vectors import get_retrieval_provider
from backend.models import (
    ArtifactEvent,
    AskRequest,
    CitationsEvent,
    CitationChip,
    ConceptUpdate,
    ConceptsEvent,
    DoneEvent,
    ErrorEvent,
    GradedEvent,
    IntentEvent,
    IndexRequest,
    IndexAcceptedResponse,
    NotebookResponse,
    QuestionEvent,
    QuizAnswerRequest,
    QuizDoneEvent,
    QuizRequest,
    StarterCard,
    StepEvent,
    SourceResponse,
    TokenEvent,
)
from backend.sandbox.runner import run_generated_analysis
from backend.storage import (
    create_artifact,
    create_quiz_attempt,
    load_dataset_profiles,
    load_all_artifacts,
    load_artifact_row,
    load_chunk_by_anchor,
    load_file_path_by_id,
    load_quiz_attempt,
    record_quiz_answer,
    upsert_concept_updates,
    validate_citation_anchors,
)
from backend.release import FakeLLMClient


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Validate runtime prerequisites and expose release diagnostics for app lifetime."""
    try:
        diagnostics = validate_runtime_configuration()
    except ConfigurationError as exc:
        application.state.startup_error = str(exc)
        raise RuntimeError(str(exc)) from None
    application.state.diagnostics = diagnostics
    application.state.release_metadata = {
        "version": diagnostics.version,
        "build_timestamp": diagnostics.build_timestamp,
        "git_commit_hash": diagnostics.git_commit_hash,
    }
    yield


app = FastAPI(title="Fieldnotes API", version=FIELDNOTES_VERSION, lifespan=lifespan)
llm_client: LLMClient | object | None = None


@app.exception_handler(ConfigurationError)
async def configuration_error_handler(_request: Request, exc: ConfigurationError) -> JSONResponse:
    return error_response(exc=exc, request_id="req_startup", context={"route": "configuration"})


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return error_response(exc=exc, request_id=request_id_for(request), context={"route": str(request.url.path)})


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return error_response(exc=exc, request_id=request_id_for(request), context={"route": str(request.url.path)})


@app.exception_handler(sqlite3.DatabaseError)
async def sqlite_error_handler(request: Request, exc: sqlite3.DatabaseError) -> JSONResponse:
    return error_response(exc=exc, request_id=request_id_for(request), context={"route": str(request.url.path)})


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    return error_response(exc=exc, request_id=request_id_for(request), context={"route": str(request.url.path)})


@app.get("/health")
async def get_health() -> dict[str, str]:
    diagnostics = getattr(app.state, "diagnostics", None)
    mode = determine_llm_mode()
    version = diagnostics.version if diagnostics is not None else FIELDNOTES_VERSION
    payload = {
        "status": "ok",
        "version": version,
        "mode": mode,
        "startup": "healthy",
    }
    registry_warning = workspace_manager.last_recovery_warning()
    if registry_warning:
        payload["registry_warning"] = registry_warning
    storage_warning = latest_storage_warning_message()
    if storage_warning:
        payload["storage_warning"] = storage_warning
    return payload


@app.post("/index", status_code=202)
async def post_index(request: IndexRequest) -> IndexAcceptedResponse:
    """Start background indexing run for a workspace folder."""

    workspace_root = Path(request.folder_path).expanduser().resolve()
    workspace_record = workspace_manager.register(workspace_root)
    run_id, event_hub = run_manager.create_run()
    asyncio.create_task(
        asyncio.to_thread(run_indexing, workspace_root, workspace_record.workspace_id, event_hub)
    )
    return IndexAcceptedResponse(
        status="accepted",
        workspace_id=workspace_record.workspace_id,
        run_id=run_id,
        events=f"/index/events/{run_id}",
    )


@app.get("/index/events/{run_id}")
async def get_index_events(run_id: str) -> StreamingResponse:
    """Stream indexing progress events over SSE."""

    hub = run_manager.get_hub(run_id)
    if hub is None:
        raise HTTPException(status_code=404, detail="Unknown run_id")

    queue = hub.subscribe()

    async def event_generator():
        while True:
            payload = await queue.get()
            if payload is None:
                break
            yield f"data: {payload}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.post("/ask")
async def post_ask(request: AskRequest, http_request: Request) -> StreamingResponse:
    """Stream grounded assistant output for a user question."""

    async def event_generator():
        answer_id = f"answer_{uuid4()}"
        request_id = request_id_for(http_request)
        try:
            workspace_record = workspace_manager.get(request.workspace_id)
            if workspace_record is None:
                raise ValueError(f"Unknown workspace_id: {request.workspace_id}")

            client = _get_llm_client()
            intent_result = await asyncio.to_thread(client.classify_intent, request.question)
            yield _sse(
                IntentEvent(
                    event="intent",
                    answer_id=answer_id,
                    intent=intent_result.intent,
                    targets=intent_result.targets,
                    connect=intent_result.connect,
                ).model_dump()
            )

            yield _sse(
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
                    retrieval_results = execution_context_data.retrieved_chunks
                else:
                    execution_plan = None
                    execution_context_data = None
                    retrieval_results = client.resolve_retrieval(request.question, retrieval_provider)
                if not retrieval_results:
                    retrieval_results = _load_fallback_retrieval(connection, limit=5)
            finally:
                connection.close()

            yield _sse(
                StepEvent(
                    event="step",
                    answer_id=answer_id,
                    step="retrieval",
                    label=f"retrieved {len(retrieval_results)} passages",
                    status="ok",
                ).model_dump()
            )

            yield _sse(
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
                    yield _sse(emitted_artifact.model_dump())
                emitted_artifacts.clear()
                if any(step.step_type == "execute_python" for step in execution_context_data.step_executions):
                    yield _sse(
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
                    yield _sse(
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
                    yield _sse(
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
                    yield _sse(
                        StepEvent(
                            event="step",
                            answer_id=answer_id,
                            step="codegen",
                            label=f"wrote analysis for {analysis_plan.target_file_path}",
                            status="ok",
                        ).model_dump()
                    )
                    yield _sse(
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
                    yield _sse(
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
                        yield _sse(emitted_artifact.model_dump())
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
                    answer_chunks.append(delta)
                    yield _sse(
                        TokenEvent(
                            event="token",
                            answer_id=answer_id,
                            text=delta,
                        ).model_dump()
                    )

            yield _sse(
                StepEvent(
                    event="step",
                    answer_id=answer_id,
                    step="grounding",
                    label="answer grounded",
                    status="ok",
                    ).model_dump()
                )

            raw_chips = [
                CitationChip(
                    chip_type="document",
                    label=_source_label(result.relative_path, result.anchor),
                    anchor=f"{result.file_id}#{result.anchor}",
                )
                for result in retrieval_results
            ]
            if code_chip is not None:
                raw_chips.append(code_chip)

            concepts = client.extract_concepts(request.question, retrieval_results)
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

            yield _sse(artifact_event.model_dump())

            yield _sse(
                CitationsEvent(
                    event="citations",
                    answer_id=answer_id,
                    chips=valid_chips,
                ).model_dump()
            )

            yield _sse(
                ConceptsEvent(
                    event="concepts",
                    answer_id=answer_id,
                    updates=concepts,
                ).model_dump()
            )

            yield _sse(DoneEvent(event="done", answer_id=answer_id).model_dump())
        except Exception as exc:
            yield _sse(
                sse_error_payload(
                    exc=exc,
                    request_id=request_id,
                    answer_id=answer_id,
                    context={"route": "/ask", "workspace_id": request.workspace_id},
                )
            )
            return

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.post("/quiz")
@app.post("/quiz/start")
async def post_quiz_start(request: QuizRequest, http_request: Request) -> StreamingResponse:
    """Start one grounded quiz question for the selected workspace."""

    async def event_generator():
        request_id = request_id_for(http_request)
        try:
            workspace_record = workspace_manager.get(request.workspace_id)
            if workspace_record is None:
                raise ValueError(f"Unknown workspace_id: {request.workspace_id}")
            client = _get_llm_client()

            connection = connect_sqlite(workspace_record.db_path)
            try:
                retrieval_provider = get_retrieval_provider(connection)
                concept_ids = request.concept_ids or _load_quiz_concept_names(connection)
                concept_query = " ".join(concept_ids) or "important concepts"
                retrieval_results = retrieval_provider.search(concept_query, limit=5)
                if not retrieval_results:
                    retrieval_results = _load_fallback_retrieval(connection, limit=5)
                if not retrieval_results:
                    raise ValueError("No indexed content available for quiz generation")

                question = await asyncio.to_thread(
                    client.generate_quiz_question,
                    retrieval_results,
                    concept_ids,
                )
                if "#" not in question.source_anchor:
                    raise ValueError("Quiz source_anchor is not a full anchor")
                file_id, locator = question.source_anchor.split("#", 1)
                if load_chunk_by_anchor(connection, file_id, locator) is None:
                    raise ValueError(
                        f"Quiz source_anchor does not resolve to a persisted chunk: {question.source_anchor}"
                    )
                file_path = load_file_path_by_id(connection, file_id)
                if file_path is None:
                    raise ValueError(f"Unknown file for quiz source_anchor: {question.source_anchor}")
                concept_update = client.extract_concepts(
                    question.question,
                    retrieval_results,
                )
                upsert_concept_updates(connection, concept_update, source_anchor=question.source_anchor)
                concept_id = concept_update[0].concept_id if concept_update else "concept_quiz"
                concept_name = concept_update[0].name if concept_update else question.concept
                attempt_id = create_quiz_attempt(
                    connection,
                    concept_id=concept_id,
                    question=question.question,
                    options=question.options,
                    correct_index=question.correct_index,
                    source_anchor=question.source_anchor,
                )
                connection.commit()
            finally:
                connection.close()

            yield _sse(
                QuestionEvent(
                    event="question",
                    attempt_id=attempt_id,
                    index=1,
                    total=1,
                    question=question.question,
                    options=question.options,
                    source_label=f"{file_path} {locator}",
                    source_anchor=question.source_anchor,
                ).model_dump()
            )
        except Exception as exc:
            yield _sse(
                sse_error_payload(
                    exc=exc,
                    request_id=request_id,
                    answer_id=f"quiz_{uuid4()}",
                    context={"route": "/quiz/start", "workspace_id": request.workspace_id},
                )
            )
            return

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.post("/quiz/answer")
async def post_quiz_answer(request: QuizAnswerRequest, http_request: Request) -> StreamingResponse:
    """Grade one persisted quiz attempt and update concept state."""

    async def event_generator():
        request_id = request_id_for(http_request)
        try:
            workspace_record = workspace_manager.get(request.workspace_id)
            if workspace_record is None:
                raise ValueError(f"Unknown workspace_id: {request.workspace_id}")

            connection = connect_sqlite(workspace_record.db_path)
            try:
                attempt = load_quiz_attempt(connection, request.attempt_id)
                if attempt is None:
                    raise ValueError(f"Unknown attempt_id: {request.attempt_id}")
                updated_attempt = record_quiz_answer(connection, request.attempt_id, request.chosen_index)
                if updated_attempt is None:
                    raise ValueError(f"Unable to persist quiz answer: {request.attempt_id}")

                concept_update = ConceptUpdate(
                    concept_id=str(updated_attempt["concept_id"]),
                    name=str(updated_attempt["concept_name"]),
                    state="touched" if int(updated_attempt["is_correct"]) else "shaky",
                )
                upsert_concept_updates(
                    connection,
                    [concept_update],
                    source_anchor=str(updated_attempt["source_anchor"]),
                )
                file_id, locator = str(updated_attempt["source_anchor"]).split("#", 1)
                chip = CitationChip(
                    chip_type="document",
                    label=f"{load_file_path_by_id(connection, file_id) or file_id} {locator}",
                    anchor=str(updated_attempt["source_anchor"]),
                )
                valid_chip_list = validate_citation_anchors(connection, [chip])
                if not valid_chip_list:
                    raise ValueError(
                        f"Quiz citation does not resolve to a persisted chunk: {updated_attempt['source_anchor']}"
                    )
                result_payload = json.dumps(
                    {
                        "attempt_id": request.attempt_id,
                        "is_correct": bool(int(updated_attempt["is_correct"])),
                        "chosen_index": request.chosen_index,
                        "correct_index": int(updated_attempt["correct_index"]),
                    }
                )
                artifact_card = create_artifact(
                    connection,
                    workspace_record.artifacts_dir,
                    kind="quiz_result",
                    title=f"Quiz result: {updated_attempt['concept_name']}",
                    answer_id=request.attempt_id,
                    payload_text=result_payload,
                )
                refreshed_starters = _build_refreshed_starters(connection)
                connection.commit()
            finally:
                connection.close()

            is_correct = bool(int(updated_attempt["is_correct"]))
            explanation = (
                "Correct. The answer matches the grounded source passage."
                if is_correct
                else "Not correct. Review the cited source passage for the grounded explanation."
            )
            concept_state = "touched" if is_correct else "shaky"

            yield _sse(
                GradedEvent(
                    event="graded",
                    attempt_id=request.attempt_id,
                    is_correct=is_correct,
                    correct_index=int(updated_attempt["correct_index"]),
                    explanation=explanation,
                    chip=valid_chip_list[0],
                    concept_update=ConceptUpdate(
                        concept_id=str(updated_attempt["concept_id"]),
                        name=str(updated_attempt["concept_name"]),
                        state=concept_state,
                    ),
                ).model_dump()
            )
            yield _sse(
                QuizDoneEvent(
                    event="quiz_done",
                    score=1 if is_correct else 0,
                    total=1,
                    artifact_id=artifact_card.id,
                    refreshed_starters=refreshed_starters,
                ).model_dump()
            )
        except Exception as exc:
            yield _sse(
                sse_error_payload(
                    exc=exc,
                    request_id=request_id,
                    answer_id=f"quiz_{uuid4()}",
                    context={"route": "/quiz/answer", "workspace_id": request.workspace_id, "attempt_id": request.attempt_id},
                )
            )
            return

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/notebook")
async def get_notebook(workspace_id: str) -> NotebookResponse:
    """Return persisted notebook artifact cards for one workspace."""

    workspace_record = workspace_manager.get(workspace_id)
    if workspace_record is None:
        raise HTTPException(status_code=404, detail="Unknown workspace_id")

    connection = connect_sqlite(workspace_record.db_path)
    try:
        artifacts = load_all_artifacts(connection)
    finally:
        connection.close()
    return NotebookResponse(artifacts=artifacts)


@app.get("/artifact/{artifact_id}")
async def get_artifact(artifact_id: str, workspace_id: str):
    """Return one persisted artifact payload."""

    workspace_record = workspace_manager.get(workspace_id)
    if workspace_record is None:
        raise HTTPException(status_code=404, detail="Unknown workspace_id")

    connection = connect_sqlite(workspace_record.db_path)
    try:
        artifact = load_artifact_row(connection, artifact_id)
    finally:
        connection.close()

    if artifact is None:
        raise HTTPException(status_code=404, detail="Unknown artifact_id")
    if artifact["payload_path"]:
        return FileResponse(str(artifact["payload_path"]))
    return JSONResponse(
        {
            "id": artifact["id"],
            "kind": artifact["kind"],
            "title": artifact["title"],
            "payload_text": artifact["payload_text"],
        }
    )


@app.get("/source/{file_id}/{locator:path}")
async def get_source(file_id: str, locator: str, workspace_id: str) -> SourceResponse:
    """Return persisted source text for a citation locator."""

    workspace_record = workspace_manager.get(workspace_id)
    if workspace_record is None:
        raise HTTPException(status_code=404, detail="Unknown workspace_id")

    connection = connect_sqlite(workspace_record.db_path)
    try:
        chunk = load_chunk_by_anchor(connection, file_id, locator)
        if chunk is None:
            raise HTTPException(status_code=404, detail="Unknown source anchor")
        file_path = load_file_path_by_id(connection, file_id)
    finally:
        connection.close()

    return SourceResponse(
        text=str(chunk["text"]),
        label=f"{file_path or file_id} {locator}",
        file_path=file_path or file_id,
    )


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


def _get_llm_client():
    global llm_client
    if llm_client is None:
        if determine_llm_mode() == "fake":
            llm_client = FakeLLMClient()
        else:
            llm_client = LLMClient()
    return llm_client


def _load_fallback_retrieval(connection, limit: int) -> list[RetrievalChunk]:
    rows = connection.execute(
        """
        SELECT chunks.text, chunks.anchor, chunks.file_id, files.path AS relative_path
        FROM chunks
        JOIN files ON files.id = chunks.file_id
        ORDER BY files.path, chunks.ordinal
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [
        RetrievalChunk(
            chunk=str(row["text"]),
            score=0.0,
            anchor=str(row["anchor"]),
            file_id=str(row["file_id"]),
            relative_path=str(row["relative_path"]),
        )
        for row in rows
    ]


def _source_label(relative_path: str, locator: str) -> str:
    return f"{relative_path} {locator}"


def _build_refreshed_starters(connection) -> list[StarterCard]:
    rows = connection.execute(
        """
        SELECT id, name, state, source_anchor
        FROM concepts
        ORDER BY CASE state WHEN 'shaky' THEN 0 ELSE 1 END, updated_at DESC
        LIMIT 4
        """
    ).fetchall()
    starters: list[StarterCard] = []
    for row in rows:
        file_path = ""
        source_anchor = row["source_anchor"]
        if source_anchor and "#" in str(source_anchor):
            file_id, _anchor = str(source_anchor).split("#", 1)
            file_path = load_file_path_by_id(connection, file_id) or ""
        starters.append(
            StarterCard(
                text=f"Review concept: {row['name']}",
                file_path=file_path,
                seed="practice" if row["state"] == "shaky" else "concept",
            )
        )
    return starters


def _load_quiz_concept_names(connection) -> list[str]:
    rows = connection.execute(
        """
        SELECT name
        FROM concepts
        ORDER BY CASE state WHEN 'shaky' THEN 0 ELSE 1 END, updated_at DESC
        LIMIT 5
        """
    ).fetchall()
    return [str(row["name"]) for row in rows]
