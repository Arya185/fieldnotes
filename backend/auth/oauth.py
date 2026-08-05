from __future__ import annotations

import os
from urllib.parse import urlencode

from backend.config import env_value

GOOGLE_CLIENT_ID = env_value("FIELDNOTES_GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = env_value("FIELDNOTES_GOOGLE_CLIENT_SECRET", "")
GITHUB_CLIENT_ID = env_value("FIELDNOTES_GITHUB_CLIENT_ID", "")
GITHUB_CLIENT_SECRET = env_value("FIELDNOTES_GITHUB_CLIENT_SECRET", "")
OAUTH_CALLBACK_PATH = env_value("FIELDNOTES_OAUTH_CALLBACK_PATH", "/auth/callback")

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
GITHUB_AUTH_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USERINFO_URL = "https://api.github.com/user"


def google_authorize_url(state: str, redirect_uri: str, scope: str = "openid email profile") -> str:
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "response_type": "code",
        "scope": scope,
        "redirect_uri": redirect_uri,
        "state": state,
        "prompt": "select_account",
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


def github_authorize_url(state: str, redirect_uri: str, scope: str = "read:user user:email") -> str:
    params = {
        "client_id": GITHUB_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "state": state,
        "scope": scope,
    }
    return f"{GITHUB_AUTH_URL}?{urlencode(params)}"
