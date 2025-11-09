"""SQLite helpers for event report records."""
from __future__ import annotations

import os
import sqlite3
import threading
from pathlib import Path
from typing import Optional

from ..paths import EVENTS_DB_PATH

_CONNECTION: Optional[sqlite3.Connection] = None
_LOCK = threading.Lock()


def _resolve_db_path() -> Path:
    path_text = os.getenv("EVENTS_DB_PATH")
    path = Path(path_text) if path_text else EVENTS_DB_PATH
    if not path.is_absolute():
        path = (Path(__file__).resolve().parents[1] / path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def get_connection() -> sqlite3.Connection:
    """Return a shared SQLite connection for reported events."""
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
        CREATE TABLE IF NOT EXISTS reported_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            route_line TEXT NOT NULL,
            track_side TEXT NOT NULL,
            mileage_text TEXT NOT NULL,
            mileage_meters REAL,
            photo_filename TEXT,
            longitude REAL,
            latitude REAL,
            location_title TEXT,
            location_address TEXT,
            source_type TEXT,
            source_id TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_reported_events_created_at
        ON reported_events (created_at DESC);
        """
    )
    conn.commit()


__all__ = ["get_connection"]
