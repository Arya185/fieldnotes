"""SQLite connection and schema bootstrap for Fieldnotes."""

from __future__ import annotations

import sqlite3
from pathlib import Path


CURRENT_SCHEMA_VERSION = 2

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


def connect_sqlite(db_path: Path) -> sqlite3.Connection:
    """Open SQLite connection for workspace database."""

    connection = sqlite3.connect(db_path, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON;")
    connection.execute("PRAGMA journal_mode = WAL;")
    connection.execute("PRAGMA busy_timeout = 5000;")
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
