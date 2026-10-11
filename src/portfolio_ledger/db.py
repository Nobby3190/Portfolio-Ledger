"""SQLite connection, migrations and backups."""

from __future__ import annotations

import os
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

# LEDGER_DATA_DIR points the app at another folder (demo data, testing) instead of the real one.
APP_DIR = Path(os.environ.get("LEDGER_DATA_DIR") or Path.home() / "Library" / "Application Support" / "帳本 Ledger")
MIGRATIONS = Path(__file__).parent / "migrations"
KEEP_BACKUPS = 10


class Db:
    """One connection shared by the UI and poller threads, serialized by a lock."""

    def __init__(self, path: Path | str) -> None:
        self.path = path
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        if path != ":memory:":
            self.conn.execute("PRAGMA journal_mode = WAL")
        self.lock = threading.RLock()
        self._migrate()

    def _migrate(self) -> None:
        current = self.conn.execute("PRAGMA user_version").fetchone()[0]
        for f in sorted(MIGRATIONS.glob("*.sql")):
            version = int(f.name.split("_", 1)[0])
            if version <= current:
                continue
            with self.lock:
                self.conn.executescript(f"BEGIN;\n{f.read_text()}\nPRAGMA user_version = {version};\nCOMMIT;")

    @contextmanager
    def write(self) -> Iterator[sqlite3.Connection]:
        """A transaction: commits on success, rolls back on any exception."""
        with self.lock:
            try:
                yield self.conn
                self.conn.commit()
            except BaseException:
                self.conn.rollback()
                raise

    def query(self, sql: str, params: tuple | dict = ()) -> list[sqlite3.Row]:
        with self.lock:
            return self.conn.execute(sql, params).fetchall()

    def backup_to(self, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        with self.lock, sqlite3.connect(dest) as out:
            self.conn.backup(out)


def open_app_db() -> Db:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    db = Db(APP_DIR / "data.db")
    auto_backup(db, APP_DIR / "backups")
    return db


def auto_backup(db: Db, folder: Path) -> Path:
    """Copy the database aside on every launch, keeping the newest KEEP_BACKUPS copies."""
    dest = folder / f"data-{datetime.now():%Y%m%d-%H%M%S}.db"
    db.backup_to(dest)
    for old in sorted(folder.glob("data-*.db"))[:-KEEP_BACKUPS]:
        old.unlink(missing_ok=True)
    return dest
