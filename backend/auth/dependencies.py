from __future__ import annotations

from fastapi import Depends, Request

from backend.auth.security import get_current_user
from backend.auth.models import AuthenticatedUser


def get_current_user_dependency(request: Request) -> AuthenticatedUser:
    return get_current_user(request)


def require_authenticated_user(user: AuthenticatedUser = Depends(get_current_user)) -> AuthenticatedUser:
    return user
