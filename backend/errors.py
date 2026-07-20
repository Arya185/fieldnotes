"""Public error contract and exception mapping."""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

from backend.config import ConfigurationError
from backend.db import WorkspaceStorageRecoveryError


logger = logging.getLogger("fieldnotes.api")


@dataclass(frozen=True)
class PublicError:
    code: str
    message: str
    recoverable: bool
    status_code: int


def build_public_error(exc: Exception) -> PublicError:
    text = str(exc)

    if isinstance(exc, RequestValidationError):
        return PublicError("INVALID_REQUEST", "Request payload is invalid.", True, 422)
    if isinstance(exc, ConfigurationError):
        return PublicError("MODEL_CONFIGURATION_ERROR", "Application configuration is invalid.", False, 500)
    if isinstance(exc, WorkspaceStorageRecoveryError):
        return PublicError("DATABASE_ERROR", str(exc), True, 500)
    if isinstance(exc, HTTPException):
        return _map_http_exception(exc)
    if isinstance(exc, sqlite3.DatabaseError):
        return PublicError("DATABASE_ERROR", "Workspace data is unavailable right now.", False, 500)
    if isinstance(exc, TimeoutError) or "timed out" in text.lower():
        return PublicError("TIMEOUT", "Operation took too long to complete.", True, 500)
    if "Unknown workspace_id" in text:
        return PublicError("WORKSPACE_NOT_FOUND", "Selected workspace was not found.", True, 404)
    if "Unknown run_id" in text:
        return PublicError("INVALID_REQUEST", "Requested indexing run was not found.", True, 404)
    if "Unknown artifact_id" in text:
        return PublicError("INVALID_REQUEST", "Requested artifact was not found.", True, 404)
    if "Unknown source anchor" in text:
        return PublicError("INVALID_REQUEST", "Requested source passage was not found.", True, 404)
    if "Unknown attempt_id" in text:
        return PublicError("INVALID_REQUEST", "Requested quiz attempt was not found.", True, 404)
    if "sandbox" in text.lower() or "analysis completed locally" in text.lower():
        return PublicError("SANDBOX_ERROR", "Local analysis failed to complete safely.", True, 500)
    if "Analysis sandbox" in text:
        return PublicError("SANDBOX_ERROR", "Local analysis failed to complete safely.", True, 500)
    if "OPENAI" in text or "Responses API" in text or "authentication failed" in text.lower():
        return PublicError("LIVE_API_UNAVAILABLE", "Live AI service is unavailable right now.", True, 502)
    return PublicError("INTERNAL_ERROR", "Something went wrong while processing the request.", False, 500)


def log_public_exception(
    *,
    exc: Exception,
    request_id: str,
    context: dict[str, Any],
) -> None:
    logger.error(
        "public_api_error request_id=%s exception_type=%s context=%s",
        request_id,
        type(exc).__name__,
        json.dumps(context, sort_keys=True, default=str),
        exc_info=(type(exc), exc, exc.__traceback__),
    )


def error_response(*, exc: Exception, request_id: str, context: dict[str, Any]) -> JSONResponse:
    public_error = build_public_error(exc)
    log_public_exception(exc=exc, request_id=request_id, context=context)
    return JSONResponse(
        status_code=public_error.status_code,
        content={
            "code": public_error.code,
            "message": public_error.message,
            "recoverable": public_error.recoverable,
            "request_id": request_id,
        },
    )


def sse_error_payload(*, exc: Exception, request_id: str, answer_id: str, context: dict[str, Any]) -> dict[str, Any]:
    public_error = build_public_error(exc)
    log_public_exception(exc=exc, request_id=request_id, context=context)
    return {
        "event": "error",
        "answer_id": answer_id,
        "code": public_error.code,
        "message": public_error.message,
        "recoverable": public_error.recoverable,
        "request_id": request_id,
    }


def request_id_for(request: Request) -> str:
    header_value = request.headers.get("x-request-id", "").strip()
    if header_value:
        return header_value
    import uuid

    return f"req_{uuid.uuid4()}"


def _map_http_exception(exc: HTTPException) -> PublicError:
    detail = str(exc.detail)
    if exc.status_code == 404 and "workspace" in detail.lower():
        return PublicError("WORKSPACE_NOT_FOUND", "Selected workspace was not found.", True, 404)
    if exc.status_code == 404:
        return PublicError("INVALID_REQUEST", "Requested resource was not found.", True, 404)
    if exc.status_code == 403:
        return PublicError("INVALID_REQUEST", "Request origin is not allowed.", True, 403)
    if exc.status_code == 400:
        return PublicError("INVALID_REQUEST", "Request could not be completed.", True, 400)
    return PublicError("INTERNAL_ERROR", "Something went wrong while processing the request.", False, exc.status_code)
