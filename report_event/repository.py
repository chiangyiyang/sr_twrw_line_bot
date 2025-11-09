"""Persistence helpers for reported events."""
from __future__ import annotations

from typing import List

from .database import get_connection
from .models import ReportEventRecord


def save_report(record: ReportEventRecord) -> int:
    """Persist a confirmed event report into SQLite."""
    conn = get_connection()
    with conn:
        cursor = conn.execute(
            """
            INSERT INTO reported_events (
                event_type,
                route_line,
                track_side,
                mileage_text,
                mileage_meters,
                photo_filename,
                longitude,
                latitude,
                location_title,
                location_address,
                source_type,
                source_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.event_type,
                record.route_line,
                record.track_side,
                record.mileage_text,
                record.mileage_meters,
                record.photo_filename,
                record.longitude,
                record.latitude,
                record.location_title,
                record.location_address,
                record.source_type,
                record.source_id,
            ),
        )
        record_id = int(cursor.lastrowid)
        record.id = record_id
        return record_id


def list_recent_events(limit: int = 500) -> List[ReportEventRecord]:
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT *
        FROM reported_events
        ORDER BY datetime(created_at) DESC, id DESC
        LIMIT ?
        """,
        (max(1, min(limit, 2000)),),
    ).fetchall()
    return [ReportEventRecord.from_row(row) for row in rows]
