from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend.auth.cookies import SESSION_COOKIE_NAME
from backend.auth.jwt import decode_token
from backend.auth.models import AuthenticatedUser
from backend.indexer.workspace_repository import WorkspaceRepository
from backend.indexer.registry_database import RegistryDatabase


class AuthConfig:
    enabled: bool

    def __init__(self) -> None:
        self.enabled = os.environ.get("FIELDNOTES_AUTH_ENABLED", "0") == "1"


auth_config = AuthConfig()

bearer_scheme = HTTPBearer(auto_error=False)


def get_registry_database() -> RegistryDatabase:
    from backend.config import WORKSPACE_REGISTRY_DB_PATH

    return RegistryDatabase(WORKSPACE_REGISTRY_DB_PATH)


def get_workspace_repository(database: RegistryDatabase = Depends(get_registry_database)) -> WorkspaceRepository:
    return WorkspaceRepository(database)


def _get_token_from_request(request: Request) -> str | None:
    bearer = request.headers.get("Authorization")
    if bearer and bearer.startswith("Bearer "):
        return bearer[7:]
    if SESSION_COOKIE_NAME in request.cookies:
        return request.cookies[SESSION_COOKIE_NAME]
    return None


def get_current_user(request: Request, repository: WorkspaceRepository = Depends(get_workspace_repository)) -> AuthenticatedUser | None:
    if not auth_config.enabled:
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
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing authentication token")

    try:
        payload = decode_token(token)
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authentication token") from exc

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
    if not auth_config.enabled:
        return current_user

    if current_user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

    role = repository.get_member_role(workspace_id, current_user["user_id"])
    if role is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    if role not in allowed_roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient workspace permissions")

    current_user["role"] = role
    return current_user


def require_workspace_role(workspace_id: str, allowed_roles: list[str]) -> AuthenticatedUser:
    def dependency(current_user: AuthenticatedUser = Depends(get_current_user), repository: WorkspaceRepository = Depends(get_workspace_repository)) -> AuthenticatedUser:
        if current_user is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

        if not auth_config.enabled:
            return current_user

        # Validate membership from workspace_members table.
        row = repository.database.connect().execute(
            "SELECT role FROM workspace_members WHERE workspace_id = ? AND user_id = ?",
            (workspace_id, current_user["user_id"]),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

        role = row["role"]
        if role not in allowed_roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient workspace permissions")

        current_user["role"] = role
        return current_user

    return dependency
