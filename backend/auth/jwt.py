from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import jwt

from backend.config import env_value

JWT_ALGORITHM = "HS256"
JWT_AUDIENCE = "fieldnotes"
JWT_ISSUER = "fieldnotes"

ACCESS_TOKEN_EXPIRES_SECONDS = int(env_value("FIELDNOTES_JWT_ACCESS_LIFETIME", "900"))
REFRESH_TOKEN_EXPIRES_SECONDS = int(env_value("FIELDNOTES_JWT_REFRESH_LIFETIME", "604800"))


def _jwt_secret() -> str:
    secret = os.environ.get("FIELDNOTES_JWT_SECRET")
    if not secret:
        raise RuntimeError("FIELDNOTES_JWT_SECRET is required when auth is enabled")
    return secret


def create_access_token(subject: str, email: str, provider: str, provider_id: str, role: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "email": email,
        "provider": provider,
        "provider_id": provider_id,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ACCESS_TOKEN_EXPIRES_SECONDS)).timestamp()),
        "aud": JWT_AUDIENCE,
        "iss": JWT_ISSUER,
    }
    return jwt.encode(payload, _jwt_secret(), algorithm=JWT_ALGORITHM)


def create_refresh_token(subject: str, email: str, provider: str, provider_id: str, role: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "email": email,
        "provider": provider,
        "provider_id": provider_id,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=REFRESH_TOKEN_EXPIRES_SECONDS)).timestamp()),
        "aud": JWT_AUDIENCE,
        "iss": JWT_ISSUER,
        "type": "refresh",
    }
    return jwt.encode(payload, _jwt_secret(), algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict[str, object]:
    return jwt.decode(
        token,
        _jwt_secret(),
        algorithms=[JWT_ALGORITHM],
        audience=JWT_AUDIENCE,
        issuer=JWT_ISSUER,
    )
