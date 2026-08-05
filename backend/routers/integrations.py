from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.auth.dependencies import get_current_user
from backend.auth.drive_credentials import load_drive_credentials, save_drive_credentials
from backend.auth.models import AuthenticatedUser
from backend.auth.oauth import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
from backend.config import WORKSPACE_REGISTRY_DB_PATH
from backend.indexer.registry_database import RegistryDatabase
from backend.indexer.workspace_manager import workspace_manager
from backend.services.google_drive import (
    DriveFile,
    GoogleDriveError,
    download_drive_file,
    list_drive_files,
    refresh_drive_access_token,
)

router = APIRouter()


class DriveImportRequest(BaseModel):
    workspace_id: str
    file_ids: list[str]
    folder_id: str | None = None


def _subject_for(current_user: AuthenticatedUser) -> str:
    return f"{current_user['provider']}:{current_user['provider_id']}"


async def _resolve_drive_access_token(current_user: AuthenticatedUser) -> str:
    registry = RegistryDatabase(WORKSPACE_REGISTRY_DB_PATH)
    connection = registry.connect()
    try:
        subject = _subject_for(current_user)
        credentials = load_drive_credentials(connection, subject)
        if credentials is None:
            raise HTTPException(
                status_code=401,
                detail="Google Drive is not connected. Connect it first, then retry.",
            )

        expires_at = credentials.get("expires_at")
        is_expired = False
        if expires_at:
            try:
                is_expired = datetime.fromisoformat(expires_at) <= datetime.now(timezone.utc)
            except ValueError:
                is_expired = False

        if not is_expired:
            return str(credentials["access_token"])

        refresh_token = credentials.get("refresh_token")
        if not refresh_token:
            raise HTTPException(
                status_code=401,
                detail="Google Drive access expired. Reconnect Google Drive to continue.",
            )

        try:
            refreshed = await refresh_drive_access_token(
                str(refresh_token), client_id=GOOGLE_CLIENT_ID, client_secret=GOOGLE_CLIENT_SECRET
            )
        except GoogleDriveError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc

        new_access_token = str(refreshed["access_token"])
        expires_in = refreshed.get("expires_in")
        new_expires_at = None
        if isinstance(expires_in, (int, float)):
            new_expires_at = datetime.fromtimestamp(
                datetime.now(timezone.utc).timestamp() + float(expires_in), tz=timezone.utc
            ).isoformat()
        save_drive_credentials(
            connection,
            subject,
            access_token=new_access_token,
            refresh_token=str(refresh_token),
            expires_at=new_expires_at,
            scope=credentials.get("scope"),
        )
        return new_access_token
    finally:
        connection.close()


@router.get("/integrations/google-drive/status")
def get_google_drive_status(current_user: AuthenticatedUser = Depends(get_current_user)) -> dict[str, bool]:
    """Whether the current user has connected Google Drive."""

    registry = RegistryDatabase(WORKSPACE_REGISTRY_DB_PATH)
    connection = registry.connect()
    try:
        credentials = load_drive_credentials(connection, _subject_for(current_user))
        return {"connected": credentials is not None}
    finally:
        connection.close()


@router.get("/integrations/google-drive/files")
async def get_google_drive_files(
    folder_id: str | None = None,
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, list[dict[str, object]]]:
    """List importable files in one Drive folder (or the user's root)."""

    access_token = await _resolve_drive_access_token(current_user)
    try:
        files = await list_drive_files(access_token, folder_id=folder_id)
    except GoogleDriveError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "files": [
            {"id": f.id, "name": f.name, "mime_type": f.mime_type, "importable": f.importable}
            for f in files
        ]
    }


@router.post("/integrations/google-drive/import")
async def post_google_drive_import(
    payload: DriveImportRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, list[str]]:
    """Download the selected Drive files into the workspace's local folder.

    The files land on disk exactly like any manually-added local file; the
    caller re-indexes the workspace folder afterward through the normal
    `/index` endpoint — no separate ingestion path.
    """

    workspace = workspace_manager.get(payload.workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Unknown workspace_id")

    access_token = await _resolve_drive_access_token(current_user)
    try:
        available = await list_drive_files(access_token, folder_id=payload.folder_id)
        by_id = {f.id: f for f in available}
        imported: list[str] = []
        for file_id in payload.file_ids:
            drive_file = by_id.get(file_id)
            if drive_file is None or not drive_file.importable:
                continue
            destination = await download_drive_file(access_token, drive_file, Path(workspace.root))
            imported.append(destination.name)
    except GoogleDriveError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if not imported:
        raise HTTPException(status_code=422, detail="No importable files were selected.")
    return {"imported": imported}
