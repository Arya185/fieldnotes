"""Backend entrypoint for Phase 1 indexing, ask, quiz, and artifact APIs."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from backend.agent.llm import LLMClient
from backend.config import (
    FIELDNOTES_VERSION,
    TRUSTED_ORIGINS,
    ConfigurationError,
    determine_llm_mode,
    validate_runtime_configuration,
)
from backend.db import connect_sqlite, latest_storage_warning_message
from backend.errors import error_response, request_id_for
from backend.indexer.events import run_manager
from backend.indexer.pipeline import run_indexing
from backend.indexer.workspace_manager import WorkspaceRecord, workspace_manager
from backend.models import (
    AskRequest,
    IndexRequest,
    IndexAcceptedResponse,
    NotebookResponse,
    QuizAnswerRequest,
    QuizRequest,
    SourceResponse,
)
from backend.services.ask import stream_ask_events
from backend.services.quiz import stream_quiz_answer_events, stream_quiz_start_events
from backend.storage import (
    load_all_artifacts,
    load_artifact_row,
    load_chunk_by_anchor,
    load_file_path_by_id,
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
app.add_middleware(
    CORSMiddleware,
    allow_origins=[],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
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
async def post_index(request: IndexRequest, http_request: Request) -> IndexAcceptedResponse:
    """Start background indexing run for a workspace folder."""

    _reject_browser_origin(http_request)
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
    _reject_browser_origin(http_request)
    return StreamingResponse(
        stream_ask_events(request, http_request, _get_llm_client, _sse),
        media_type="text/event-stream",
    )


@app.post("/quiz/start")
async def post_quiz_start(request: QuizRequest, http_request: Request) -> StreamingResponse:
    """Start one grounded quiz question for the selected workspace."""
    _reject_browser_origin(http_request)
    return StreamingResponse(
        stream_quiz_start_events(request, http_request, _get_llm_client, _sse),
        media_type="text/event-stream",
    )


@app.post("/quiz/answer")
async def post_quiz_answer(request: QuizAnswerRequest, http_request: Request) -> StreamingResponse:
    """Grade one persisted quiz attempt and update concept state."""
    _reject_browser_origin(http_request)
    return StreamingResponse(
        stream_quiz_answer_events(request, http_request, _sse),
        media_type="text/event-stream",
    )


def get_workspace_record(workspace_id: str) -> WorkspaceRecord:
    workspace_record = workspace_manager.get(workspace_id)
    if workspace_record is None:
        raise HTTPException(status_code=404, detail="Unknown workspace_id")
    return workspace_record


@app.get("/notebook")
async def get_notebook(workspace_record: WorkspaceRecord = Depends(get_workspace_record)) -> NotebookResponse:
    """Return persisted notebook artifact cards for one workspace."""

    connection = connect_sqlite(workspace_record.db_path)
    try:
        artifacts = load_all_artifacts(connection)
    finally:
        connection.close()
    return NotebookResponse(artifacts=artifacts)


@app.get("/artifact/{artifact_id}")
async def get_artifact(artifact_id: str, workspace_record: WorkspaceRecord = Depends(get_workspace_record)):
    """Return one persisted artifact payload."""

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
async def get_source(
    file_id: str,
    locator: str,
    workspace_record: WorkspaceRecord = Depends(get_workspace_record),
) -> SourceResponse:
    """Return persisted source text for a citation locator."""

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


def _reject_browser_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    referer = request.headers.get("referer")
    if origin and not _is_trusted_browser_origin(origin):
        raise HTTPException(status_code=403, detail="Untrusted browser origin.")
    if referer:
        referer_origin = _origin_from_url(referer)
        if not _is_trusted_browser_origin(referer_origin):
            raise HTTPException(status_code=403, detail="Untrusted browser origin.")


def _origin_from_url(value: str) -> str:
    parts = urlsplit(value)
    if not parts.scheme or not parts.netloc:
        return ""
    return f"{parts.scheme}://{parts.netloc}"


def _is_trusted_browser_origin(origin: str) -> bool:
    if not origin:
        return True
    if origin in TRUSTED_ORIGINS:
        return True

    parts = urlsplit(origin)
    if parts.scheme not in {"http", "https"}:
        return False
    return parts.hostname in {"localhost", "127.0.0.1"}
