"""SQLite connection and schema bootstrap for Fieldnotes."""

from __future__ import annotations

import logging
import os
import json
import sqlite3
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger("fieldnotes.storage")

CURRENT_SCHEMA_VERSION = 2
REPAIRED_WORKSPACE_WARNING = "Workspace storage was repaired."
REINDEX_REQUIRED_WORKSPACE_WARNING = "Workspace storage requires re-indexing."
_STORAGE_WARNINGS: dict[str, str] = {}

BASE_SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS files (
  id            TEXT PRIMARY KEY,
  path          TEXT NOT NULL UNIQUE,
  kind          TEXT NOT NULL CHECK (kind IN ('pdf','pptx','docx','md','txt','csv')),
  display_name  TEXT NOT NULL,
  size_bytes    INTEGER NOT NULL,
  parse_status  TEXT NOT NULL CHECK (parse_status IN ('parsed','failed','skipped')),
  parse_summary TEXT,
  created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chunks (
  id         TEXT PRIMARY KEY,
  file_id    TEXT NOT NULL REFERENCES files(id) ON DELETE CASCADE,
  ordinal    INTEGER NOT NULL,
  text       TEXT NOT NULL,
  anchor     TEXT NOT NULL,
  UNIQUE (file_id, ordinal)
);
CREATE INDEX IF NOT EXISTS idx_chunks_file ON chunks(file_id);

CREATE TABLE IF NOT EXISTS dataset_profiles (
  file_id      TEXT PRIMARY KEY REFERENCES files(id) ON DELETE CASCADE,
  profile_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS concepts (
  id            TEXT PRIMARY KEY,
  name          TEXT NOT NULL UNIQUE,
  state         TEXT NOT NULL CHECK (state IN ('touched','shaky')),
  touch_count   INTEGER NOT NULL DEFAULT 1,
  miss_count    INTEGER NOT NULL DEFAULT 0,
  source_anchor TEXT,
  updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS quiz_attempts (
  id            TEXT PRIMARY KEY,
  concept_id    TEXT NOT NULL REFERENCES concepts(id),
  question      TEXT NOT NULL,
  options_json  TEXT NOT NULL,
  correct_index INTEGER NOT NULL,
  chosen_index  INTEGER,
  is_correct    INTEGER,
  source_anchor TEXT NOT NULL,
  created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_quiz_concept ON quiz_attempts(concept_id);

CREATE TABLE IF NOT EXISTS artifacts (
  id           TEXT PRIMARY KEY,
  kind         TEXT NOT NULL CHECK (kind IN ('chart','explainer','quiz_result','script')),
  title        TEXT NOT NULL,
  payload_path TEXT,
  payload_text TEXT,
  answer_id    TEXT,
  created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_artifacts_answer ON artifacts(answer_id);

CREATE TABLE IF NOT EXISTS workspace_meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
"""

SCHEMA_VERSION_SQL = """
CREATE TABLE IF NOT EXISTS schema_version (
  version INTEGER NOT NULL
);
"""

MIGRATION_2_SQL = """
CREATE TABLE IF NOT EXISTS embeddings (
  chunk_id      TEXT PRIMARY KEY REFERENCES chunks(id) ON DELETE CASCADE,
  provider      TEXT NOT NULL,
  model         TEXT NOT NULL,
  content_hash  TEXT NOT NULL,
  vector_json   TEXT NOT NULL,
  created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_embeddings_provider_model
  ON embeddings(provider, model);
"""


class WorkspaceStorageRecoveryError(RuntimeError):
    """Raised when workspace storage cannot be rebuilt automatically."""


def connect_sqlite(db_path: Path, *, validate_integrity: bool = True) -> sqlite3.Connection:
    """Open SQLite connection for workspace database."""

    if validate_integrity and db_path.exists():
        _ensure_workspace_storage_healthy(db_path)

    connection = _open_sqlite_connection(db_path)
    if validate_integrity and db_path.exists():
        _assert_integrity(connection)
    return connection


def initialize_schema(connection: sqlite3.Connection) -> None:
    """Create or migrate schema objects without data loss."""

    connection.executescript(BASE_SCHEMA_SQL)
    version = _ensure_schema_version_table(connection)
    _apply_migrations(connection, version)
    connection.commit()


def _table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    row = connection.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table' AND name = ?
        """,
        (table_name,),
    ).fetchone()
    return row is not None


def _detect_legacy_schema(connection: sqlite3.Connection) -> bool:
    legacy_tables = {
        "files",
        "chunks",
        "dataset_profiles",
        "concepts",
        "quiz_attempts",
        "artifacts",
        "workspace_meta",
    }
    present = {
        str(row["name"])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    return bool(legacy_tables & present)


def _ensure_schema_version_table(connection: sqlite3.Connection) -> int:
    if _table_exists(connection, "schema_version"):
        row = connection.execute(
            "SELECT version FROM schema_version ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
        if row is None:
            connection.execute("INSERT INTO schema_version (version) VALUES (?)", (1,))
            return 1
        return int(row["version"])

    inferred_version = 1 if _detect_legacy_schema(connection) else 1
    connection.executescript(SCHEMA_VERSION_SQL)
    connection.execute("DELETE FROM schema_version")
    connection.execute(
        "INSERT INTO schema_version (version) VALUES (?)",
        (inferred_version,),
    )
    return inferred_version


def _apply_migrations(connection: sqlite3.Connection, current_version: int) -> None:
    version = current_version
    if version < 2:
        connection.executescript(MIGRATION_2_SQL)
        connection.execute("DELETE FROM schema_version")
        connection.execute(
            "INSERT INTO schema_version (version) VALUES (?)",
            (2,),
        )
        version = 2
    else:
        connection.executescript(MIGRATION_2_SQL)

    if version > CURRENT_SCHEMA_VERSION:
        raise RuntimeError(
            f"Unsupported schema version {version}; expected <= {CURRENT_SCHEMA_VERSION}"
        )


def latest_storage_warning(db_path: Path) -> str | None:
    return _STORAGE_WARNINGS.get(str(db_path.resolve()))


def clear_storage_warning(db_path: Path) -> None:
    _STORAGE_WARNINGS.pop(str(db_path.resolve()), None)


def latest_storage_warning_message() -> str | None:
    if not _STORAGE_WARNINGS:
        return None
    return next(reversed(_STORAGE_WARNINGS.values()))


def _open_sqlite_connection(db_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path, check_same_thread=False)
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON;")
        connection.execute("PRAGMA journal_mode = WAL;")
        connection.execute("PRAGMA busy_timeout = 5000;")
        return connection
    except Exception:
        connection.close()
        raise


def _ensure_workspace_storage_healthy(db_path: Path) -> None:
    clear_storage_warning(db_path)
    try:
        connection = _open_sqlite_connection(db_path)
    except sqlite3.DatabaseError as exc:
        _repair_workspace_storage(db_path, exc)
        return
    try:
        _assert_integrity(connection)
    except sqlite3.DatabaseError as exc:
        connection.close()
        _repair_workspace_storage(db_path, exc)
        return
    finally:
        with suppress(Exception):
            connection.close()


def _assert_integrity(connection: sqlite3.Connection) -> None:
    rows = connection.execute("PRAGMA integrity_check;").fetchall()
    messages = [str(row[0]) for row in rows]
    if any(message.lower() != "ok" for message in messages):
        raise sqlite3.DatabaseError("; ".join(messages))


def _repair_workspace_storage(db_path: Path, initial_exc: Exception) -> None:
    logger.warning(
        "workspace storage recovery started for %s",
        db_path,
        exc_info=(type(initial_exc), initial_exc, initial_exc.__traceback__),
    )
    if _attempt_wal_recovery(db_path):
        _STORAGE_WARNINGS[str(db_path.resolve())] = REPAIRED_WORKSPACE_WARNING
        logger.warning("workspace storage recovered after WAL checkpoint: %s", db_path)
        return

    workspace_root = db_path.parent.parent
    quarantine_paths = _quarantine_database_files(db_path)
    _create_replacement_database(db_path)

    if _workspace_has_rebuild_sources(workspace_root):
        _rebuild_workspace_storage(workspace_root, db_path)
        _STORAGE_WARNINGS[str(db_path.resolve())] = REPAIRED_WORKSPACE_WARNING
        logger.warning("workspace storage rebuilt from source files: %s", db_path)
        return

    _rehydrate_artifact_metadata(db_path)
    _STORAGE_WARNINGS[str(db_path.resolve())] = REINDEX_REQUIRED_WORKSPACE_WARNING
    logger.warning(
        "workspace storage recreated without source rebuild: %s quarantined=%s",
        db_path,
        [str(path) for path in quarantine_paths],
    )
    raise WorkspaceStorageRecoveryError(REINDEX_REQUIRED_WORKSPACE_WARNING)


def _attempt_wal_recovery(db_path: Path) -> bool:
    try:
        connection = _open_sqlite_connection(db_path)
    except sqlite3.DatabaseError:
        return False
    try:
        with suppress(sqlite3.DatabaseError):
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE);").fetchall()
        connection.close()
        reopened = _open_sqlite_connection(db_path)
        try:
            _assert_integrity(reopened)
            return True
        finally:
            reopened.close()
    except sqlite3.DatabaseError:
        return False
    finally:
        with suppress(Exception):
            connection.close()


def _quarantine_database_files(db_path: Path) -> list[Path]:
    timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H%M%SZ")
    quarantined: list[Path] = []
    for suffix_path in (db_path, Path(f"{db_path}-wal"), Path(f"{db_path}-shm")):
        if not suffix_path.exists():
            continue
        target = suffix_path.with_name(f"{suffix_path.name}.corrupt-{timestamp}")
        counter = 1
        while target.exists():
            target = suffix_path.with_name(f"{suffix_path.name}.corrupt-{timestamp}-{counter}")
            counter += 1
        suffix_path.replace(target)
        quarantined.append(target)
    return quarantined


def _create_replacement_database(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = _open_sqlite_connection(db_path)
    try:
        initialize_schema(connection)
    finally:
        connection.close()


def _workspace_has_rebuild_sources(workspace_root: Path) -> bool:
    from backend.indexer.discovery import discover_files

    return bool(discover_files(workspace_root))


def _rebuild_workspace_storage(workspace_root: Path, db_path: Path) -> None:
    from backend.indexer.events import EventStreamHub
    from backend.indexer.pipeline import run_indexing

    workspace_id = _load_workspace_id(workspace_root) or f"recovered_{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"
    run_indexing(workspace_root, workspace_id, EventStreamHub())
    _rehydrate_artifact_metadata(db_path)


def _load_workspace_id(workspace_root: Path) -> str | None:
    metadata_path = workspace_root / ".fieldnotes" / "workspace.json"
    if not metadata_path.exists():
        return None
    try:
        payload = json_load_file(metadata_path)
    except Exception:
        return None
    workspace_id = payload.get("workspace_id")
    return workspace_id if isinstance(workspace_id, str) and workspace_id.strip() else None


def _rehydrate_artifact_metadata(db_path: Path) -> None:
    artifacts_dir = db_path.parent / "artifacts"
    if not artifacts_dir.exists():
        return
    connection = _open_sqlite_connection(db_path)
    try:
        existing_paths = {
            str(row["payload_path"])
            for row in connection.execute("SELECT payload_path FROM artifacts WHERE payload_path IS NOT NULL").fetchall()
        }
        for artifact_path in sorted(artifacts_dir.iterdir()):
            if not artifact_path.is_file() or str(artifact_path) in existing_paths:
                continue
            connection.execute(
                """
                INSERT INTO artifacts (id, kind, title, payload_path, payload_text, answer_id, created_at)
                VALUES (?, ?, ?, ?, NULL, ?, ?)
                """,
                (
                    f"artifact_recovered_{artifact_path.stem.replace('-', '_')}",
                    _artifact_kind_for_path(artifact_path),
                    _artifact_title_for_path(artifact_path),
                    str(artifact_path),
                    _answer_id_for_recovered_artifact(artifact_path),
                    datetime.now(UTC).isoformat(),
                ),
            )
        connection.commit()
    finally:
        connection.close()


def _artifact_kind_for_path(path: Path) -> str:
    if path.suffix.lower() == ".png":
        return "chart"
    if path.suffix.lower() == ".py":
        return "script"
    return "explainer"


def _artifact_title_for_path(path: Path) -> str:
    if path.suffix.lower() == ".png":
        return f"Recovered chart: {path.name}"
    if path.suffix.lower() == ".py":
        return f"Recovered script: {path.name}"
    return f"Recovered artifact: {path.name}"


def _answer_id_for_recovered_artifact(path: Path) -> str | None:
    name = path.name
    if name.endswith("_analysis.py"):
        return name[: -len("_analysis.py")]
    if name.endswith("_chart.png"):
        return name[: -len("_chart.png")]
    return None


def json_load_file(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
