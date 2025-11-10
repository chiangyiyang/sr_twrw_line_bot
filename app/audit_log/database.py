"""SQLite helpers for audit log storage."""
from __future__ import annotations

import os
import sqlite3
import threading
from pathlib import Path
from typing import Optional

from ..paths import AUDIT_LOG_DB_PATH

_CONNECTION: Optional[sqlite3.Connection] = None
_LOCK = threading.Lock()


def _resolve_db_path() -> Path:
    override = os.getenv("AUDIT_LOG_DB_PATH")
    path = Path(override) if override else AUDIT_LOG_DB_PATH
    if not path.is_absolute():
        path = (Path(__file__).resolve().parents[1] / path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _apply_schema(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            action_type TEXT NOT NULL,
            channel TEXT,
            actor_type TEXT,
            actor_id TEXT,
            actor_name TEXT,
            ip_address TEXT,
            resource_type TEXT,
            resource_id TEXT,
            status TEXT NOT NULL,
            message TEXT,
            details TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_audit_logs_created_at
        ON audit_logs (created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_audit_logs_action_type
        ON audit_logs (action_type);
        """
    )
    conn.commit()


def get_connection() -> sqlite3.Connection:
    global _CONNECTION
    if _CONNECTION is None:
        with _LOCK:
            if _CONNECTION is None:
                conn = sqlite3.connect(_resolve_db_path(), check_same_thread=False)
                conn.row_factory = sqlite3.Row
                _apply_schema(conn)
                _CONNECTION = conn
    return _CONNECTION


__all__ = ["get_connection", "_CONNECTION"]
