"""Google Drive import: list and download files into a local workspace folder.

This is the only integration-specific code in the app. Once a file lands on
disk here, it is indexed through the exact same `backend/indexer/pipeline.py`
path as any locally-chosen file — there is no parallel ingestion path. The
Drive OAuth token is used only for this one-time list/download; it is never
attached to the imported file or needed again afterward.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import httpx

DRIVE_FILES_URL = "https://www.googleapis.com/drive/v3/files"
DRIVE_TOKEN_URL = "https://oauth2.googleapis.com/token"

# Native Google Docs/Sheets/Slides types can't be downloaded directly — they
# must be exported to one of the supported local formats.
EXPORT_MIME_TYPES = {
    "application/vnd.google-apps.document": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".docx",
    ),
    "application/vnd.google-apps.presentation": (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".pptx",
    ),
    "application/vnd.google-apps.spreadsheet": ("text/csv", ".csv"),
}

# Regular (non-Google-native) files we know how to index locally.
SUPPORTED_MIME_EXTENSIONS = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "text/csv": ".csv",
    "text/markdown": ".md",
    "text/plain": ".txt",
}


class GoogleDriveError(RuntimeError):
    """Raised when a Drive API call fails or credentials are invalid."""


@dataclass(frozen=True)
class DriveFile:
    id: str
    name: str
    mime_type: str
    importable: bool


async def refresh_drive_access_token(
    refresh_token: str, *, client_id: str, client_secret: str
) -> dict[str, object]:
    """Exchange a refresh token for a new short-lived Drive access token."""

    async with httpx.AsyncClient() as client:
        response = await client.post(
            DRIVE_TOKEN_URL,
            data={
                "refresh_token": refresh_token,
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "refresh_token",
            },
            timeout=20.0,
        )
        if response.status_code >= 400:
            raise GoogleDriveError(f"Failed to refresh Google Drive access token: {response.text}")
        return response.json()


async def list_drive_files(access_token: str, *, folder_id: str | None = None) -> list[DriveFile]:
    """List files in one Drive folder (or "shared with me" root when omitted)."""

    query_parts = ["trashed = false"]
    if folder_id:
        query_parts.append(f"'{folder_id}' in parents")
    query = " and ".join(query_parts)

    async with httpx.AsyncClient() as client:
        response = await client.get(
            DRIVE_FILES_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            params={
                "q": query,
                "fields": "files(id,name,mimeType)",
                "pageSize": 100,
            },
            timeout=20.0,
        )
        if response.status_code == 401:
            raise GoogleDriveError("Google Drive access token expired or invalid.")
        if response.status_code >= 400:
            raise GoogleDriveError(f"Google Drive file listing failed: {response.text}")
        payload = response.json()

    files: list[DriveFile] = []
    for item in payload.get("files", []):
        mime_type = str(item.get("mimeType", ""))
        importable = mime_type in EXPORT_MIME_TYPES or mime_type in SUPPORTED_MIME_EXTENSIONS
        files.append(
            DriveFile(
                id=str(item["id"]),
                name=str(item.get("name", item["id"])),
                mime_type=mime_type,
                importable=importable,
            )
        )
    return files


def _target_filename(name: str, mime_type: str) -> str | None:
    if mime_type in EXPORT_MIME_TYPES:
        _, extension = EXPORT_MIME_TYPES[mime_type]
    elif mime_type in SUPPORTED_MIME_EXTENSIONS:
        extension = SUPPORTED_MIME_EXTENSIONS[mime_type]
    else:
        return None
    if name.lower().endswith(extension):
        return name
    return f"{name}{extension}"


async def download_drive_file(access_token: str, drive_file: DriveFile, destination_dir: Path) -> Path:
    """Download (or export) one Drive file into `destination_dir`. Returns the written path."""

    filename = _target_filename(drive_file.name, drive_file.mime_type)
    if filename is None:
        raise GoogleDriveError(f"Unsupported Drive file type for import: {drive_file.mime_type}")

    if drive_file.mime_type in EXPORT_MIME_TYPES:
        export_mime_type, _ = EXPORT_MIME_TYPES[drive_file.mime_type]
        url = f"{DRIVE_FILES_URL}/{drive_file.id}/export"
        params = {"mimeType": export_mime_type}
    else:
        url = f"{DRIVE_FILES_URL}/{drive_file.id}"
        params = {"alt": "media"}

    async with httpx.AsyncClient() as client:
        response = await client.get(
            url,
            headers={"Authorization": f"Bearer {access_token}"},
            params=params,
            timeout=60.0,
        )
        if response.status_code == 401:
            raise GoogleDriveError("Google Drive access token expired or invalid.")
        if response.status_code >= 400:
            raise GoogleDriveError(f"Failed to download Drive file {drive_file.name}: {response.text}")
        content = response.content

    destination_dir.mkdir(parents=True, exist_ok=True)
    destination_path = destination_dir / filename
    destination_path.write_bytes(content)
    return destination_path
