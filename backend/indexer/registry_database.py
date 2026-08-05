"""Registry database bootstrap and migration helpers."""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from backend.migrations import forget_registry_migration, migrate_registry_database

logger = logging.getLogger("fieldnotes.registry")


class RegistryDatabase:
    """Abstract registry database connection and schema management."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.last_recovery_warning: str | None = None
        self._ensure_schema()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON;")
        connection.execute("PRAGMA journal_mode = WAL;")
        connection.execute("PRAGMA synchronous = NORMAL;")
        connection.execute("PRAGMA busy_timeout = 5000;")
        return connection

    def _ensure_schema(self) -> None:
        try:
            if self.db_path.exists() and not self._has_valid_sqlite_header(self.db_path):
                raise sqlite3.DatabaseError("registry database file header is invalid")

            migrate_registry_database(self.db_path)
        except sqlite3.DatabaseError as exc:
            self._recover_database(exc)

    def _has_valid_sqlite_header(self, path: Path) -> bool:
        try:
            with path.open("rb") as handle:
                return handle.read(16) == b"SQLite format 3\x00"
        except OSError:
            return False

    def _recover_database(self, exc: Exception) -> None:
        logger.warning("registry database recovery: %s", exc, exc_info=(type(exc), exc, exc.__traceback__))
        self.last_recovery_warning = "Registry database could not be read and was recreated."
        self._quarantine_database()
        # The file at self.db_path is now quarantined-and-replaced; drop the
        # stale per-process "already migrated" marker before re-migrating.
        forget_registry_migration(self.db_path)
        self._initialize_schema()

    def _initialize_schema(self) -> None:
        migrate_registry_database(self.db_path)

    def _quarantine_database(self) -> None:
        if not self.db_path.exists():
            return

        timestamp = sqlite3.datetime.datetime.utcnow().strftime("%Y%m%d%H%M%S")
        quarantine_base = self.db_path.with_name(f"{self.db_path.name}.corrupt-{timestamp}")

        self._move_path(self.db_path, quarantine_base)

        for sidecar_suffix in ("-wal", "-shm"):
            sidecar = Path(str(self.db_path) + sidecar_suffix)
            if sidecar.exists():
                self._move_path(sidecar, Path(str(quarantine_base) + sidecar_suffix))

    def _move_path(self, source: Path, destination: Path) -> None:
        target = destination
        suffix = 1
        while target.exists():
            target = destination.with_name(f"{destination.name}-{suffix}")
            suffix += 1
        try:
            source.replace(target)
        except OSError:
            logger.warning("Could not quarantine registry database file %s", source)
