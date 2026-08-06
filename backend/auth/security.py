from __future__ import annotations

import logging
import os
import secrets
import time
from urllib.parse import urlsplit

import jwt
from fastapi import Depends, HTTPException, Request, status

from backend.auth.cookies import CSRF_COOKIE_NAME, SESSION_COOKIE_NAME
from backend.auth.jwt import decode_token
from backend.auth.models import AuthenticatedUser
from backend.config import TRUSTED_ORIGINS
from backend.indexer.registry_database import RegistryDatabase
from backend.indexer.workspace_repository import WorkspaceRepository

logger = logging.getLogger("fieldnotes.auth")

CSRF_HEADER_NAME = "X-CSRF-Token"
_LOCAL_ENVIRONMENTS = {"", "local", "development", "dev", "test"}


class AuthConfig:
    enabled: bool
    explicit: bool
    raw_value: str | None

    def __init__(self) -> None:
        self.refresh()

    def refresh(self) -> None:
        self.raw_value = os.environ.get("FIELDNOTES_AUTH_ENABLED")
        self.explicit = self.raw_value is not None
        self.enabled = str(self.raw_value).strip() == "1"


class InMemoryRateLimiter:
    def __init__(self) -> None:
        self._buckets: dict[str, tuple[float, float]] = {}

    def allow(self, key: str, *, capacity: int, refill_period_seconds: float) -> bool:
        now = time.monotonic()
        tokens, updated_at = self._buckets.get(key, (float(capacity), now))
        elapsed = max(0.0, now - updated_at)
        refill_rate = float(capacity) / refill_period_seconds
        tokens = min(float(capacity), tokens + elapsed * refill_rate)
        if tokens < 1.0:
            self._buckets[key] = (tokens, now)
            return False
        self._buckets[key] = (tokens - 1.0, now)
        return True


auth_config = AuthConfig()
rate_limiter = InMemoryRateLimiter()


def current_environment_name() -> str:
    return (
        os.environ.get("FIELDNOTES_ENV")
        or os.environ.get("ENVIRONMENT")
        or "local"
    ).strip().lower()


def is_non_local_environment() -> bool:
    return current_environment_name() not in _LOCAL_ENVIRONMENTS


def validate_auth_runtime_configuration() -> str:
    auth_config.refresh()
    if is_non_local_environment() and not auth_config.explicit:
        raise RuntimeError(
            "FIELDNOTES_AUTH_ENABLED must be explicitly set when FIELDNOTES_ENV/ENVIRONMENT is non-local."
        )
    if auth_config.enabled:
        return "enabled"
    logger.warning(
        "Authentication disabled. Synthetic local owner mode active for every request."
    )
    return "synthetic_local_owner"


def get_registry_database() -> RegistryDatabase:
    from backend.config import WORKSPACE_REGISTRY_DB_PATH

    return RegistryDatabase(WORKSPACE_REGISTRY_DB_PATH)


def get_workspace_repository(
    database: RegistryDatabase = Depends(get_registry_database),
) -> WorkspaceRepository:
    return WorkspaceRepository(database)


def _get_token_from_request(request: Request) -> str | None:
    bearer = request.headers.get("Authorization")
    if bearer and bearer.startswith("Bearer "):
        return bearer[7:]
    if SESSION_COOKIE_NAME in request.cookies:
        return request.cookies[SESSION_COOKIE_NAME]
    return None


def get_current_user(
    request: Request,
    repository: WorkspaceRepository = Depends(get_workspace_repository),
) -> AuthenticatedUser | None:
    del repository
    auth_config.refresh()
    if not auth_config.enabled:
        logger.warning(
            "Synthetic local owner mode served request path=%s environment=%s",
            request.url.path,
            current_environment_name(),
        )
        return {
            "user_id": "local_admin",
            "email": "local@fieldnotes.local",
            "name": "Local Admin",
            "provider": "local",
            "provider_id": "local_admin",
            "role": "owner",
        }

    token = _get_token_from_request(request)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token",
        )

    try:
        payload = decode_token(token)
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
        ) from exc

    user_id = str(payload.get("sub"))
    role = str(payload.get("role", "viewer"))
    return {
        "user_id": user_id,
        "email": str(payload.get("email", "")),
        "name": str(payload.get("name", "")),
        "provider": str(payload.get("provider", "")),
        "provider_id": str(payload.get("provider_id", "")),
        "role": role,
    }


def assert_workspace_access(
    workspace_id: str,
    current_user: AuthenticatedUser,
    repository: WorkspaceRepository,
    allowed_roles: list[str],
) -> AuthenticatedUser:
    auth_config.refresh()
    if not auth_config.enabled:
        return current_user

    if current_user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

    role = repository.get_member_role(workspace_id, current_user["user_id"])
    if role is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    if role not in allowed_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient workspace permissions",
        )

    current_user["role"] = role
    return current_user


def validate_csrf(request: Request) -> None:
    auth_config.refresh()
    if request.method.upper() not in {"POST", "PUT", "PATCH", "DELETE"}:
        return
    if not auth_config.enabled:
        return
    session_token = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_token:
        return
    expected = request.cookies.get(CSRF_COOKIE_NAME)
    provided = request.headers.get(CSRF_HEADER_NAME)
    if not expected or not provided or not secrets.compare_digest(expected, provided):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF validation failed",
        )


def reject_browser_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    referer = request.headers.get("referer")
    if origin and not _is_trusted_browser_origin(request, origin):
        raise HTTPException(status_code=403, detail="Untrusted browser origin.")
    if referer:
        referer_origin = _origin_from_url(referer)
        if not _is_trusted_browser_origin(request, referer_origin):
            raise HTTPException(status_code=403, detail="Untrusted browser origin.")


def _origin_from_url(value: str) -> str:
    parts = urlsplit(value)
    if not parts.scheme or not parts.netloc:
        return ""
    return f"{parts.scheme}://{parts.netloc}"


def _is_trusted_browser_origin(request: Request, origin: str) -> bool:
    if not origin:
        return True
    if origin in TRUSTED_ORIGINS:
        return True
    if origin == _origin_from_url(str(request.base_url)):
        return True

    parts = urlsplit(origin)
    if parts.scheme not in {"http", "https"}:
        return False
    return parts.hostname in {"localhost", "127.0.0.1"}


def rate_limit_subject(
    request: Request,
    current_user: AuthenticatedUser | None = None,
) -> str:
    if current_user is not None:
        return f"user:{current_user['user_id']}"
    client_host = request.client.host if request.client is not None else "unknown"
    return f"ip:{client_host}"


RATE_LIMIT_DISABLED_ENV = "FIELDNOTES_RATE_LIMIT_DISABLED"


def enforce_rate_limit(
    request: Request,
    *,
    scope: str,
    current_user: AuthenticatedUser | None = None,
    capacity: int,
    refill_period_seconds: float,
) -> None:
    # rate_limiter is process-global, keyed by user/IP with no per-request
    # isolation. Under `unittest discover`, every test file shares one
    # process and one synthetic "local_admin" user, so without this escape
    # hatch, sustained test volume across the whole suite trips buckets
    # that individual tests never intended to exercise. tests/__init__.py
    # sets this before any test module imports backend.main; only
    # test_phase1_security.py (which owns the rate-limiting tests) turns
    # enforcement back on for itself.
    if os.environ.get(RATE_LIMIT_DISABLED_ENV) == "1":
        return
    key = f"{scope}:{rate_limit_subject(request, current_user)}"
    if rate_limiter.allow(
        key,
        capacity=capacity,
        refill_period_seconds=refill_period_seconds,
    ):
        return
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="Rate limit exceeded. Retry later.",
    )


def require_workspace_role(workspace_id: str, allowed_roles: list[str]) -> AuthenticatedUser:
    def dependency(
        current_user: AuthenticatedUser = Depends(get_current_user),
        repository: WorkspaceRepository = Depends(get_workspace_repository),
    ) -> AuthenticatedUser:
        auth_config.refresh()
        if current_user is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

        if not auth_config.enabled:
            return current_user

        return assert_workspace_access(workspace_id, current_user, repository, allowed_roles)

    return dependency
