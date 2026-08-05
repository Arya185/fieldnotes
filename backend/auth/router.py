from __future__ import annotations

import json
import os
import secrets
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse

from backend.auth.cookies import SESSION_COOKIE_NAME, access_cookie_header, clear_cookie_header, refresh_cookie_header
from backend.auth.jwt import create_access_token, create_refresh_token, decode_token
from backend.auth.models import TokenResponse
from backend.auth.drive_credentials import save_drive_credentials
from backend.auth.oauth import GITHUB_CLIENT_ID, GITHUB_CLIENT_SECRET, GITHUB_TOKEN_URL, GITHUB_USERINFO_URL, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_DRIVE_IMPORT_SCOPE, GOOGLE_TOKEN_URL, GOOGLE_USERINFO_URL, github_authorize_url, google_authorize_url, OAUTH_CALLBACK_PATH
from backend.auth.security import _get_token_from_request, auth_config, get_current_user
from backend.config import WORKSPACE_REGISTRY_DB_PATH
from backend.indexer.registry_database import RegistryDatabase

router = APIRouter()


def _build_redirect_url(request: Request, path: str) -> str:
    base = request.url._url.rstrip("/")
    return urljoin(base, path)


@router.get("/auth/providers")
async def list_auth_providers() -> dict[str, bool]:
    return {
        "google": bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET),
        "github": bool(GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET),
    }


@router.get("/auth/login/google")
async def login_google(request: Request) -> dict[str, str]:
    if not auth_config.enabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Authentication disabled")
    state = secrets.token_urlsafe(16)
    redirect_uri = _build_redirect_url(request, f"{OAUTH_CALLBACK_PATH}?provider=google")
    return {"redirect_url": google_authorize_url(state, redirect_uri)}


@router.get("/auth/login/github")
async def login_github(request: Request) -> dict[str, str]:
    if not auth_config.enabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Authentication disabled")
    state = secrets.token_urlsafe(16)
    redirect_uri = _build_redirect_url(request, f"{OAUTH_CALLBACK_PATH}?provider=github")
    return {"redirect_url": github_authorize_url(state, redirect_uri)}


@router.get("/auth/login/google-drive")
async def login_google_drive(request: Request) -> dict[str, str]:
    """Start the Google OAuth consent flow with the added Drive read-only scope.

    Separate from the plain login flow so a normal sign-in never requests
    more access than it needs; this one is only triggered by the explicit
    "Import from Google Drive" action.
    """

    if not auth_config.enabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Authentication disabled")
    state = secrets.token_urlsafe(16)
    redirect_uri = _build_redirect_url(request, f"{OAUTH_CALLBACK_PATH}?provider=google&purpose=drive")
    return {
        "redirect_url": google_authorize_url(
            state,
            redirect_uri,
            scope=GOOGLE_DRIVE_IMPORT_SCOPE,
            access_type="offline",
            prompt="consent",
        )
    }


async def _exchange_token(url: str, data: dict[str, Any], headers: dict[str, str] | None = None) -> dict[str, Any]:
    async with httpx.AsyncClient() as client:
        response = await client.post(url, data=data, headers=headers or {}, timeout=20.0)
        response.raise_for_status()
        return response.json()


async def _fetch_google_userinfo(access_token: str) -> dict[str, Any]:
    async with httpx.AsyncClient() as client:
        response = await client.get(GOOGLE_USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"}, timeout=20.0)
        response.raise_for_status()
        return response.json()


async def _fetch_github_userinfo(access_token: str) -> dict[str, Any]:
    async with httpx.AsyncClient() as client:
        response = await client.get(GITHUB_USERINFO_URL, headers={"Authorization": f"token {access_token}"}, timeout=20.0)
        response.raise_for_status()
        return response.json()


@router.get("/auth/callback")
async def oauth_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    provider: str | None = None,
    purpose: str | None = None,
) -> RedirectResponse:
    if not auth_config.enabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Authentication disabled")
    if not code or not provider:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing OAuth code or provider")

    callback_query = "?provider=google&purpose=drive" if provider == "google" and purpose == "drive" else f"?provider={provider}"
    redirect_uri = _build_redirect_url(request, f"{OAUTH_CALLBACK_PATH}{callback_query}")
    if provider == "google":
        token_data = {
            "code": code,
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
        token_response = await _exchange_token(GOOGLE_TOKEN_URL, token_data)
        userinfo = await _fetch_google_userinfo(str(token_response["access_token"]))
        user_id = str(userinfo.get("sub", ""))
        email = str(userinfo.get("email", ""))
        name = str(userinfo.get("name", email))
        provider_id = user_id
        drive_access_token = str(token_response.get("access_token", ""))
        drive_refresh_token = token_response.get("refresh_token")
        drive_expires_in = token_response.get("expires_in")
        drive_scope = token_response.get("scope")
    elif provider == "github":
        token_data = {
            "code": code,
            "client_id": GITHUB_CLIENT_ID,
            "client_secret": GITHUB_CLIENT_SECRET,
            "redirect_uri": redirect_uri,
        }
        token_response = await _exchange_token(GITHUB_TOKEN_URL, token_data, headers={"Accept": "application/json"})
        access_token = str(token_response.get("access_token", ""))
        userinfo = await _fetch_github_userinfo(access_token)
        user_id = str(userinfo.get("id", ""))
        email = str(userinfo.get("email", "")) or f"{user_id}@github.local"
        name = str(userinfo.get("name", email))
        provider_id = user_id
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown OAuth provider")

    subject = f"{provider}:{provider_id}"

    if provider == "google" and purpose == "drive":
        expires_at = None
        if isinstance(drive_expires_in, (int, float)):
            expires_at = datetime.fromtimestamp(
                datetime.now(timezone.utc).timestamp() + float(drive_expires_in), tz=timezone.utc
            ).isoformat()
        registry = RegistryDatabase(WORKSPACE_REGISTRY_DB_PATH)
        connection = registry.connect()
        try:
            save_drive_credentials(
                connection,
                subject,
                access_token=drive_access_token,
                refresh_token=drive_refresh_token,
                expires_at=expires_at,
                scope=drive_scope,
            )
        finally:
            connection.close()

    access_token = create_access_token(subject, email, provider, provider_id, role="viewer")
    refresh_token = create_refresh_token(subject, email, provider, provider_id, role="viewer")

    response = RedirectResponse(url="/")
    response.headers["Set-Cookie"] = access_cookie_header(access_token)
    response.headers.append("Set-Cookie", refresh_cookie_header(refresh_token))
    return response


@router.post("/auth/refresh")
async def refresh_token(request: Request, response: Response) -> TokenResponse:
    if not auth_config.enabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Authentication disabled")

    token = request.cookies.get("fieldnotes_refresh")
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing refresh token")

    try:
        payload = decode_token(token)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token") from exc
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token type")

    subject = str(payload.get("sub"))
    email = str(payload.get("email", ""))
    provider = str(payload.get("provider", ""))
    provider_id = str(payload.get("provider_id", ""))
    role = str(payload.get("role", "viewer"))

    access_token = create_access_token(subject, email, provider, provider_id, role=role)
    new_refresh_token = create_refresh_token(subject, email, provider, provider_id, role=role)

    response.headers["Set-Cookie"] = access_cookie_header(access_token)
    response.headers.append("Set-Cookie", refresh_cookie_header(new_refresh_token))
    return TokenResponse(access_token=access_token, expires_in=int(os.environ.get("FIELDNOTES_JWT_ACCESS_LIFETIME", "900")))


@router.post("/auth/logout")
async def logout(response: Response) -> dict[str, str]:
    response.headers["Set-Cookie"] = clear_cookie_header(SESSION_COOKIE_NAME)
    response.headers.append("Set-Cookie", clear_cookie_header("fieldnotes_refresh"))
    return {"status": "logged_out"}


@router.get("/auth/status")
async def auth_status(request: Request) -> dict[str, object]:
    if not auth_config.enabled:
        return {
            "auth_enabled": False,
            "authenticated": True,
            "user": {
                "user_id": "local_admin",
                "email": "local@fieldnotes.local",
                "name": "Local Admin",
                "provider": "local",
                "provider_id": "local_admin",
                "role": "owner",
            },
            "providers": {"google": False, "github": False},
        }

    token = _get_token_from_request(request)
    if not token:
        return {"auth_enabled": True, "authenticated": False, "providers": await list_auth_providers()}

    try:
        user = get_current_user(request)
    except HTTPException:
        return {"auth_enabled": True, "authenticated": False, "providers": await list_auth_providers()}

    return {"auth_enabled": True, "authenticated": True, "user": user, "providers": await list_auth_providers()}
