"""
db.py — SQLite database layer for Brewster.

Handles connection management, schema migrations, and all read/write operations.
Each machine only ever writes its own rows (machine_id-scoped), so concurrent
iCloud/Dropbox syncs are safe with WAL mode enabled.
"""

from __future__ import annotations

import sqlite3
import logging
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator, Optional

log = logging.getLogger(__name__)

# Bump this whenever you add a migration in MIGRATIONS below.
CURRENT_SCHEMA_VERSION = 1

MIGRATIONS: dict[int, str] = {
    1: """
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS machines (
            id            INTEGER PRIMARY KEY,
            hostname      TEXT    NOT NULL,
            label         TEXT    NOT NULL,
            platform      TEXT    NOT NULL,
            macos_version TEXT,
            brew_prefix   TEXT,
            last_seen     TEXT    NOT NULL,
            UNIQUE(hostname)
        );

        CREATE TABLE IF NOT EXISTS formulae (
            id           INTEGER PRIMARY KEY,
            machine_id   INTEGER NOT NULL REFERENCES machines(id) ON DELETE CASCADE,
            name         TEXT    NOT NULL,
            version      TEXT    NOT NULL,
            tap          TEXT,
            installed_on TEXT,
            UNIQUE(machine_id, name)
        );

        CREATE TABLE IF NOT EXISTS casks (
            id           INTEGER PRIMARY KEY,
            machine_id   INTEGER NOT NULL REFERENCES machines(id) ON DELETE CASCADE,
            name         TEXT    NOT NULL,
            version      TEXT    NOT NULL,
            tap          TEXT,
            installed_on TEXT,
            UNIQUE(machine_id, name)
        );

        INSERT INTO schema_version (version) VALUES (1);
    """,
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class BrewsterDB:
    """
    Thin wrapper around a sqlite3 connection.

    Usage:
        db = BrewsterDB(path)
        db.open()          # or: with BrewsterDB(path) as db:
        db.close()
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._conn: Optional[sqlite3.Connection] = None

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    def open(self) -> None:
        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True)

        log.debug("Opening DB at %s", path)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row

        # WAL mode: reads don't block writes; safer with cloud sync interruptions.
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")

        self._migrate()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "BrewsterDB":
        self.open()
        return self

    def __exit__(self, *_) -> None:
        self.close()

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("DB is not open. Call open() first.")
        return self._conn

    # ------------------------------------------------------------------
    # Schema migrations
    # ------------------------------------------------------------------

    def _current_version(self) -> int:
        try:
            row = self.conn.execute(
                "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
            ).fetchone()
            return int(row["version"]) if row else 0
        except sqlite3.OperationalError:
            return 0  # schema_version table doesn't exist yet

    def _migrate(self) -> None:
        current = self._current_version()
        if current >= CURRENT_SCHEMA_VERSION:
            return

        log.debug("Migrating DB from version %d → %d", current, CURRENT_SCHEMA_VERSION)
        for version in sorted(MIGRATIONS):
            if version > current:
                log.debug("Applying migration %d", version)
                self.conn.executescript(MIGRATIONS[version])
                self.conn.commit()

    # ------------------------------------------------------------------
    # Machine operations
    # ------------------------------------------------------------------

    def upsert_machine(
        self,
        hostname: str,
        label: str,
        platform: str,
        macos_version: Optional[str],
        brew_prefix: Optional[str],
    ) -> int:
        """Insert or update this machine record. Returns the machine's row id."""
        self.conn.execute(
            """
            INSERT INTO machines (hostname, label, platform, macos_version, brew_prefix, last_seen)
            VALUES (:hostname, :label, :platform, :macos_version, :brew_prefix, :last_seen)
            ON CONFLICT(hostname) DO UPDATE SET
                label         = excluded.label,
                platform      = excluded.platform,
                macos_version = excluded.macos_version,
                brew_prefix   = excluded.brew_prefix,
                last_seen     = excluded.last_seen
            """,
            dict(
                hostname=hostname,
                label=label,
                platform=platform,
                macos_version=macos_version,
                brew_prefix=brew_prefix,
                last_seen=_now_iso(),
            ),
        )
        self.conn.commit()
        row = self.conn.execute(
            "SELECT id FROM machines WHERE hostname = ?", (hostname,)
        ).fetchone()
        return int(row["id"])

    def get_machine_by_name(self, name: str) -> Optional[sqlite3.Row]:
        """Look up a machine by label or hostname (label takes priority)."""
        row = self.conn.execute(
            "SELECT * FROM machines WHERE label = ? OR hostname = ? LIMIT 1",
            (name, name),
        ).fetchone()
        return row

    def list_machines(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM machines ORDER BY label"
        ).fetchall()

    # ------------------------------------------------------------------
    # Formula operations
    # ------------------------------------------------------------------

    def replace_formulae(
        self,
        machine_id: int,
        packages: list[dict],
    ) -> None:
        """
        Atomically replace all formula rows for this machine.
        packages: list of dicts with keys: name, version, tap (optional)
        """
        with self.conn:
            self.conn.execute(
                "DELETE FROM formulae WHERE machine_id = ?", (machine_id,)
            )
            self.conn.executemany(
                """
                INSERT INTO formulae (machine_id, name, version, tap, installed_on)
                VALUES (:machine_id, :name, :version, :tap, :installed_on)
                """,
                [
                    dict(
                        machine_id=machine_id,
                        name=p["name"],
                        version=p["version"],
                        tap=p.get("tap"),
                        installed_on=_now_iso(),
                    )
                    for p in packages
                ],
            )

    def get_formulae(self, machine_id: int) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM formulae WHERE machine_id = ? ORDER BY name",
            (machine_id,),
        ).fetchall()

    # ------------------------------------------------------------------
    # Cask operations
    # ------------------------------------------------------------------

    def replace_casks(
        self,
        machine_id: int,
        casks: list[dict],
    ) -> None:
        """Atomically replace all cask rows for this machine."""
        with self.conn:
            self.conn.execute(
                "DELETE FROM casks WHERE machine_id = ?", (machine_id,)
            )
            self.conn.executemany(
                """
                INSERT INTO casks (machine_id, name, version, tap, installed_on)
                VALUES (:machine_id, :name, :version, :tap, :installed_on)
                """,
                [
                    dict(
                        machine_id=machine_id,
                        name=c["name"],
                        version=c["version"],
                        tap=c.get("tap"),
                        installed_on=_now_iso(),
                    )
                    for c in casks
                ],
            )

    def get_casks(self, machine_id: int) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM casks WHERE machine_id = ? ORDER BY name",
            (machine_id,),
        ).fetchall()

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def stats(self) -> dict:
        machines = self.conn.execute("SELECT COUNT(*) as n FROM machines").fetchone()["n"]
        formulae = self.conn.execute("SELECT COUNT(*) as n FROM formulae").fetchone()["n"]
        casks = self.conn.execute("SELECT COUNT(*) as n FROM casks").fetchone()["n"]
        return {"machines": machines, "formulae": formulae, "casks": casks}
