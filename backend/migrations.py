from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Callable

import sqlalchemy as sa
from alembic import command
from alembic.config import Config

ROOT_DIR = Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = ROOT_DIR / "migrations"
REGISTRY_SCRIPT_LOCATION = MIGRATIONS_DIR / "registry"
WORKSPACE_SCRIPT_LOCATION = MIGRATIONS_DIR / "workspace"
REGISTRY_BASELINE_REVISION = "registry_0001"
WORKSPACE_BASELINE_REVISION = "workspace_0001"

# Alembic's upgrade("head") is not a cheap no-op once a database is already
# current: it opens a connection, inspects alembic_version, and walks the
# script graph every time. migrate_workspace_database/migrate_registry_database
# are called from db.py's connect_sqlite() and RegistryDatabase.__init__(),
# both of which run on effectively every request — so without a per-process
# gate, every request pays full migration overhead, and concurrent requests
# hitting a brand-new (not-yet-migrated) database race to run the same
# upgrade batch at once. Cache "already at head as of this process" per
# resolved path, and hold the lock for the actual upgrade so only one
# migration runs per path even under concurrent first access.
#
# Any code path that deletes/replaces the on-disk file at a given path
# (corruption recovery / quarantine-and-recreate) MUST call
# forget_workspace_migration()/forget_registry_migration() first, or this
# cache will wrongly skip migrating the replacement file.
_migration_lock = threading.Lock()
_migrated_workspace_dbs: set[str] = set()
_migrated_registry_dbs: set[str] = set()


def _cache_key(db_path: Path) -> str:
    return str(db_path.resolve())


def forget_workspace_migration(db_path: Path) -> None:
    """Drop the per-process migration marker for one workspace DB path."""

    with _migration_lock:
        _migrated_workspace_dbs.discard(_cache_key(db_path))


def forget_registry_migration(db_path: Path) -> None:
    """Drop the per-process migration marker for one registry DB path."""

    with _migration_lock:
        _migrated_registry_dbs.discard(_cache_key(db_path))


def _sqlite_url(db_path: Path) -> str:
    return f"sqlite:///{db_path.resolve()}"


def _build_alembic_config(script_location: Path, db_path: Path) -> Config:
    config = Config()
    config.set_main_option("script_location", str(script_location))
    config.set_main_option("sqlalchemy.url", _sqlite_url(db_path))
    config.set_main_option("prepend_sys_path", str(ROOT_DIR))
    return config


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


def _legacy_registry_schema_present(connection: sqlite3.Connection) -> bool:
    return _table_exists(connection, "workspaces") and _table_exists(connection, "users")


def _legacy_workspace_schema_present(connection: sqlite3.Connection) -> bool:
    return _table_exists(connection, "files") and _table_exists(connection, "chunks")


# workspace_0001's baseline schema (see migrations/workspace/versions) includes
# schema_version and embeddings tables. Those two were historically added by an
# ad-hoc runtime migration in backend/db.py, not by the original CREATE TABLE
# script for legacy databases, so an old on-disk workspace DB that predates
# that ad-hoc migration having ever run may have "files"/"chunks" but be
# missing schema_version/embeddings. Stamping such a DB as already-at-head
# (see _stamp_if_legacy) without backfilling those tables first would mark it
# up to date while actually leaving it short two tables the app depends on.
_WORKSPACE_SCHEMA_VERSION_SQL = """
CREATE TABLE IF NOT EXISTS schema_version (
  version INTEGER NOT NULL
);
"""

_WORKSPACE_EMBEDDINGS_TABLE_SQL = """
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

_WORKSPACE_BASELINE_SCHEMA_VERSION = 2


def _backfill_legacy_workspace_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(_WORKSPACE_SCHEMA_VERSION_SQL)
    connection.executescript(_WORKSPACE_EMBEDDINGS_TABLE_SQL)
    row = connection.execute(
        "SELECT version FROM schema_version ORDER BY rowid DESC LIMIT 1"
    ).fetchone()
    if row is None or int(row[0]) < _WORKSPACE_BASELINE_SCHEMA_VERSION:
        connection.execute("DELETE FROM schema_version")
        connection.execute(
            "INSERT INTO schema_version (version) VALUES (?)",
            (_WORKSPACE_BASELINE_SCHEMA_VERSION,),
        )
    # Alembic's SQLAlchemy Connection wrapper (built right after this call,
    # see _wrap_raw_connection below) manages its own transaction boundary on
    # the same underlying sqlite3 connection; commit here so the backfill is
    # durable before that wrapper takes over, instead of risking it being
    # rolled back or left pending across the handoff.
    connection.commit()


def _has_alembic_version(connection: sqlite3.Connection) -> bool:
    return _table_exists(connection, "alembic_version")


def _wrap_raw_connection(raw_connection: sqlite3.Connection) -> sa.engine.Connection:
    """Adapt an existing raw sqlite3 connection for Alembic's SQLAlchemy-based context.

    Alembic's `context.configure(connection=...)` requires a SQLAlchemy
    `Connection` (it reads `.dialect` off it); a bare `sqlite3.Connection`
    doesn't have that attribute and raises AttributeError. `creator` makes
    the engine reuse the existing raw connection instead of opening a new
    one (so the migration participates in the caller's already-open
    connection/transaction), and StaticPool means closing the returned
    SQLAlchemy Connection does not close the underlying raw connection —
    the caller still owns that lifecycle.
    """
    engine = sa.create_engine("sqlite://", creator=lambda: raw_connection, poolclass=sa.pool.StaticPool)
    return engine.connect()


def _stamp_if_legacy(
    *,
    connection: sqlite3.Connection,
    config: Config,
    baseline_revision: str,
    legacy_detector,
    pre_stamp: Callable[[sqlite3.Connection], None] | None = None,
) -> None:
    if _has_alembic_version(connection):
        return
    if not legacy_detector(connection):
        return
    if pre_stamp is not None:
        pre_stamp(connection)
    wrapped_connection = _wrap_raw_connection(connection)
    try:
        config.attributes["connection"] = wrapped_connection
        command.stamp(config, baseline_revision)
    finally:
        wrapped_connection.close()
        # config is a single object shared with whatever upgrade() call
        # follows this stamp. Leaving a now-closed connection behind in
        # config.attributes would make that follow-up call try to reuse it
        # (ResourceClosedError) instead of building its own fresh connection.
        config.attributes.pop("connection", None)


def _upgrade(
    *,
    db_path: Path,
    script_location: Path,
    baseline_revision: str,
    legacy_detector,
    connection: sqlite3.Connection | None = None,
    pre_stamp: Callable[[sqlite3.Connection], None] | None = None,
) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    config = _build_alembic_config(script_location, db_path)
    if connection is not None:
        _stamp_if_legacy(
            connection=connection,
            config=config,
            baseline_revision=baseline_revision,
            legacy_detector=legacy_detector,
            pre_stamp=pre_stamp,
        )
        wrapped_connection = _wrap_raw_connection(connection)
        try:
            config.attributes["connection"] = wrapped_connection
            command.upgrade(config, "head")
        finally:
            wrapped_connection.close()
        return

    raw_connection = sqlite3.connect(db_path)
    try:
        with raw_connection:
            _stamp_if_legacy(
                connection=raw_connection,
                config=config,
                baseline_revision=baseline_revision,
                legacy_detector=legacy_detector,
                pre_stamp=pre_stamp,
            )
    finally:
        raw_connection.close()

    command.upgrade(config, "head")


def migrate_registry_database(
    db_path: Path,
    *,
    connection: sqlite3.Connection | None = None,
) -> None:
    key = _cache_key(db_path)
    with _migration_lock:
        if key in _migrated_registry_dbs:
            return
        _upgrade(
            db_path=db_path,
            script_location=REGISTRY_SCRIPT_LOCATION,
            baseline_revision=REGISTRY_BASELINE_REVISION,
            legacy_detector=_legacy_registry_schema_present,
            connection=connection,
        )
        _migrated_registry_dbs.add(key)


def migrate_workspace_database(
    db_path: Path,
    *,
    connection: sqlite3.Connection | None = None,
) -> None:
    key = _cache_key(db_path)
    with _migration_lock:
        if key in _migrated_workspace_dbs:
            return
        _upgrade(
            db_path=db_path,
            script_location=WORKSPACE_SCRIPT_LOCATION,
            baseline_revision=WORKSPACE_BASELINE_REVISION,
            legacy_detector=_legacy_workspace_schema_present,
            connection=connection,
            pre_stamp=_backfill_legacy_workspace_schema,
        )
        _migrated_workspace_dbs.add(key)


def migrate_all_workspace_databases(registry_db_path: Path) -> list[Path]:
    if not registry_db_path.exists():
        return []

    migrated: list[Path] = []
    connection = sqlite3.connect(registry_db_path)
    try:
        connection.row_factory = sqlite3.Row
        if not _table_exists(connection, "workspaces"):
            return migrated
        rows = connection.execute("SELECT root FROM workspaces ORDER BY created_at").fetchall()
    finally:
        connection.close()

    for row in rows:
        workspace_root = Path(str(row["root"]))
        db_path = workspace_root / ".fieldnotes" / "fieldnotes.db"
        if not db_path.exists():
            continue
        migrate_workspace_database(db_path)
        migrated.append(db_path)
    return migrated
