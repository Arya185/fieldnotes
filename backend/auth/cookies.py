from __future__ import annotations

from datetime import datetime, timedelta
from http import cookies

from backend.config import env_value

COOKIE_DOMAIN = env_value("FIELDNOTES_COOKIE_DOMAIN", "")
COOKIE_SAMESITE = env_value("FIELDNOTES_COOKIE_SAMESITE", "Lax")
COOKIE_SECURE = env_value("FIELDNOTES_COOKIE_SECURE", "1") == "1"
ACCESS_COOKIE_AGE = int(env_value("FIELDNOTES_SESSION_COOKIE_AGE", "900"))
REFRESH_COOKIE_AGE = int(env_value("FIELDNOTES_REFRESH_COOKIE_AGE", "604800"))
OAUTH_STATE_COOKIE_AGE = int(env_value("FIELDNOTES_OAUTH_STATE_COOKIE_AGE", "600"))


def _prefixed_cookie_name(base_name: str) -> str:
    if COOKIE_SECURE and not COOKIE_DOMAIN:
        return f"__Host-{base_name}"
    if COOKIE_SECURE:
        return f"__Secure-{base_name}"
    return base_name


SESSION_COOKIE_NAME = _prefixed_cookie_name(
    env_value("FIELDNOTES_SESSION_COOKIE_NAME", "fieldnotes_session")
)
REFRESH_COOKIE_NAME = _prefixed_cookie_name(
    env_value("FIELDNOTES_REFRESH_COOKIE_NAME", "fieldnotes_refresh")
)
CSRF_COOKIE_NAME = _prefixed_cookie_name(
    env_value("FIELDNOTES_CSRF_COOKIE_NAME", "fieldnotes_csrf")
)
OAUTH_STATE_COOKIE_NAME = _prefixed_cookie_name(
    env_value("FIELDNOTES_OAUTH_STATE_COOKIE_NAME", "fieldnotes_oauth_state")
)


def build_cookie_header(
    name: str,
    value: str,
    max_age: int,
    path: str = "/",
    *,
    http_only: bool = True,
) -> str:
    attributes = [f"{name}={value}", f"SameSite={COOKIE_SAMESITE}", f"Path={path}"]
    if http_only:
        attributes.append("HttpOnly")
    if COOKIE_SECURE:
        attributes.append("Secure")
    if COOKIE_DOMAIN:
        attributes.append(f"Domain={COOKIE_DOMAIN}")
    expires = (datetime.utcnow() + timedelta(seconds=max_age)).strftime("%a, %d %b %Y %H:%M:%S GMT")
    attributes.append(f"Max-Age={max_age}")
    attributes.append(f"Expires={expires}")
    return "; ".join(attributes)


def access_cookie_header(token: str) -> str:
    return build_cookie_header(SESSION_COOKIE_NAME, token, ACCESS_COOKIE_AGE)


def refresh_cookie_header(token: str) -> str:
    return build_cookie_header(REFRESH_COOKIE_NAME, token, REFRESH_COOKIE_AGE)


def csrf_cookie_header(token: str) -> str:
    return build_cookie_header(CSRF_COOKIE_NAME, token, ACCESS_COOKIE_AGE, http_only=False)


def oauth_state_cookie_header(value: str) -> str:
    return build_cookie_header(OAUTH_STATE_COOKIE_NAME, value, OAUTH_STATE_COOKIE_AGE)


def clear_cookie_header(name: str) -> str:
    morsel = cookies.Morsel()
    morsel.set(name, "", "")
    morsel["httponly"] = True
    morsel["secure"] = str(COOKIE_SECURE).lower()
    morsel["samesite"] = COOKIE_SAMESITE
    morsel["path"] = "/"
    morsel["expires"] = "Thu, 01 Jan 1970 00:00:00 GMT"
    morsel["max-age"] = "0"
    return morsel.OutputString()
