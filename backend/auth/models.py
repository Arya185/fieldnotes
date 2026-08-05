from __future__ import annotations

from datetime import datetime
from typing import TypedDict

from pydantic import BaseModel


class UserPayload(BaseModel):
    user_id: str
    email: str
    name: str
    provider: str
    provider_id: str
    issued_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int


class AuthenticatedUser(TypedDict):
    user_id: str
    email: str
    name: str
    provider: str
    provider_id: str
    role: str
