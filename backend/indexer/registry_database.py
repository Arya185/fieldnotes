"""Registry database bootstrap and migration helpers."""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger("fieldnotes.registry")

SCHEMA_VERSION = 1

SQL_FILES = [
    Path(__file__).resolve().parent.parent / "sql" / "registry.sql",
    Path(__file__).resolve().parent.parent / "sql" / "workspace.sql",
]


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

            with self.connect() as connection:
                for sql_file in SQL_FILES:
                    connection.executescript(sql_file.read_text(encoding="utf-8"))
                self._ensure_schema_version(connection)
                connection.commit()
        except sqlite3.DatabaseError as exc:
            self._recover_database(exc)

    def _has_valid_sqlite_header(self, path: Path) -> bool:
        try:
            with path.open("rb") as handle:
                return handle.read(16) == b"SQLite format 3\x00"
        except OSError:
            return False

    def _ensure_schema_version(self, connection: sqlite3.Connection) -> None:
        row = connection.execute("SELECT version FROM schema_version ORDER BY rowid DESC LIMIT 1").fetchone()
        if row is None:
            connection.execute("DELETE FROM schema_version")
            connection.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))

    def _recover_database(self, exc: Exception) -> None:
        logger.warning("registry database recovery: %s", exc, exc_info=(type(exc), exc, exc.__traceback__))
        self.last_recovery_warning = "Registry database could not be read and was recreated."
        self._quarantine_database()
        self._initialize_schema()

    def _initialize_schema(self) -> None:
        with self.connect() as connection:
            for sql_file in SQL_FILES:
                connection.executescript(sql_file.read_text(encoding="utf-8"))
            self._ensure_schema_version(connection)
            connection.commit()

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
