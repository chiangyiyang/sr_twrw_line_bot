"""SQLite helpers for rainfall data."""
from __future__ import annotations

import os
import sqlite3
import threading
from pathlib import Path
from typing import Optional

from ..paths import RAINFALL_DB_PATH

_CONNECTION: Optional[sqlite3.Connection] = None
_LOCK = threading.Lock()


def _resolve_db_path() -> Path:
    path_text = os.getenv("RAINFALL_DB_PATH")
    path = Path(path_text) if path_text else RAINFALL_DB_PATH
    if not path.is_absolute():
        path = (Path(__file__).resolve().parents[1] / path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def get_connection() -> sqlite3.Connection:
    """Return a shared SQLite connection, creating the database if necessary."""
    global _CONNECTION
    if _CONNECTION is None:
        with _LOCK:
            if _CONNECTION is None:
                db_path = _resolve_db_path()
                conn = sqlite3.connect(db_path, check_same_thread=False)
                conn.row_factory = sqlite3.Row
                _apply_schema(conn)
                _CONNECTION = conn
    return _CONNECTION


def _apply_schema(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS stations (
            station_id TEXT PRIMARY KEY,
            station_name TEXT NOT NULL,
            city TEXT,
            town TEXT,
            attribute TEXT,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            elevation REAL
        );

        CREATE TABLE IF NOT EXISTS observations (
            station_id TEXT NOT NULL,
            obs_time TEXT NOT NULL,
            min_10 REAL,
            hour_1 REAL,
            hour_3 REAL,
            hour_6 REAL,
            hour_12 REAL,
            hour_24 REAL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (station_id, obs_time),
            FOREIGN KEY (station_id) REFERENCES stations (station_id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_observations_obs_time
        ON observations (obs_time DESC);

        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS poller_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            last_success_at TEXT
        )
        """
    )

    conn.commit()


__all__ = ["get_connection"]
