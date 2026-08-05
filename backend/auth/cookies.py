from __future__ import annotations

from datetime import datetime, timedelta
from http import cookies
from typing import Any

from backend.config import env_value

SESSION_COOKIE_NAME = env_value("FIELDNOTES_SESSION_COOKIE_NAME", "fieldnotes_session")
CSRF_COOKIE_NAME = env_value("FIELDNOTES_CSRF_COOKIE_NAME", "fieldnotes_csrf")

COOKIE_DOMAIN = env_value("FIELDNOTES_COOKIE_DOMAIN", "")
COOKIE_SAMESITE = env_value("FIELDNOTES_COOKIE_SAMESITE", "Lax")
COOKIE_SECURE = env_value("FIELDNOTES_COOKIE_SECURE", "1") == "1"
ACCESS_COOKIE_AGE = int(env_value("FIELDNOTES_SESSION_COOKIE_AGE", "900"))
REFRESH_COOKIE_AGE = int(env_value("FIELDNOTES_REFRESH_COOKIE_AGE", "604800"))


def build_cookie_header(name: str, value: str, max_age: int, path: str = "/") -> str:
    attributes = [f"{name}={value}", "HttpOnly", f"SameSite={COOKIE_SAMESITE}", f"Path={path}"]
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
    return build_cookie_header("fieldnotes_refresh", token, REFRESH_COOKIE_AGE)


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
