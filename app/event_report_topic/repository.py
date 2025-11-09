"""Persistence helpers for reported events."""
from __future__ import annotations

from typing import Iterable, List, Mapping, Optional, Sequence, Tuple

from .database import get_connection
from .models import ReportEventRecord

_EVENT_COLUMNS = (
    "event_type",
    "route_line",
    "track_side",
    "mileage_text",
    "mileage_meters",
    "photo_filename",
    "longitude",
    "latitude",
    "location_title",
    "location_address",
    "source_type",
    "source_id",
)


def _extract_value(source, key: str):
    if isinstance(source, Mapping):
        return source.get(key)
    return getattr(source, key, None)


def _insert_record(conn, source) -> int:
    placeholders = ",".join("?" for _ in _EVENT_COLUMNS)
    column_sql = ", ".join(_EVENT_COLUMNS)
    values = [_extract_value(source, col) for col in _EVENT_COLUMNS]
    cursor = conn.execute(
        f"""
        INSERT INTO reported_events ({column_sql})
        VALUES ({placeholders})
        """,
        values,
    )
    return int(cursor.lastrowid)


def save_report(record: ReportEventRecord) -> int:
    """Persist a confirmed event report into SQLite."""
    conn = get_connection()
    with conn:
        record_id = _insert_record(conn, record)
        record.id = record_id
        return record_id


def create_event(payload: Mapping[str, object]) -> ReportEventRecord:
    conn = get_connection()
    with conn:
        event_id = _insert_record(conn, payload)
    return get_event(event_id)


def update_event(event_id: int, updates: Mapping[str, object]) -> Optional[ReportEventRecord]:
    fields = []
    values = []
    for column in _EVENT_COLUMNS:
        if column in updates:
            fields.append(f"{column} = ?")
            values.append(updates.get(column))
    if not fields:
        return get_event(event_id)

    conn = get_connection()
    with conn:
        values.append(event_id)
        conn.execute(
            f"""
            UPDATE reported_events
            SET {", ".join(fields)}
            WHERE id = ?
            """,
            values,
        )
    return get_event(event_id)


def delete_event(event_id: int) -> bool:
    conn = get_connection()
    with conn:
        cursor = conn.execute("DELETE FROM reported_events WHERE id = ?", (event_id,))
        return cursor.rowcount > 0


def bulk_delete(event_ids: Sequence[int]) -> int:
    if not event_ids:
        return 0
    conn = get_connection()
    with conn:
        cursor = conn.execute(
            f"DELETE FROM reported_events WHERE id IN ({','.join('?' for _ in event_ids)})",
            tuple(event_ids),
        )
        return cursor.rowcount


def get_event(event_id: int) -> Optional[ReportEventRecord]:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM reported_events WHERE id = ?",
        (event_id,),
    ).fetchone()
    return ReportEventRecord.from_row(row) if row else None


def get_events_by_ids(event_ids: Sequence[int]) -> List[ReportEventRecord]:
    if not event_ids:
        return []
    conn = get_connection()
    rows = conn.execute(
        f"""
        SELECT *
        FROM reported_events
        WHERE id IN ({",".join("?" for _ in event_ids)})
        """,
        tuple(event_ids),
    ).fetchall()
    return [ReportEventRecord.from_row(row) for row in rows]


def _build_filters(
    event_type: Optional[str] = None,
    route_line: Optional[str] = None,
    track_side: Optional[str] = None,
    has_photo: Optional[bool] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    keyword: Optional[str] = None,
) -> Tuple[str, List[object]]:
    conditions = []
    params: List[object] = []
    if event_type:
        conditions.append("event_type = ?")
        params.append(event_type)
    if route_line:
        conditions.append("route_line = ?")
        params.append(route_line)
    if track_side:
        conditions.append("track_side = ?")
        params.append(track_side)
    if has_photo is True:
        conditions.append("photo_filename IS NOT NULL AND photo_filename <> ''")
    elif has_photo is False:
        conditions.append("photo_filename IS NULL OR photo_filename = ''")
    if start_time:
        conditions.append("datetime(created_at) >= datetime(?)")
        params.append(start_time)
    if end_time:
        conditions.append("datetime(created_at) <= datetime(?)")
        params.append(end_time)
    if keyword:
        conditions.append(
            "(location_title LIKE ? OR location_address LIKE ? OR mileage_text LIKE ?)"
        )
        like = f"%{keyword}%"
        params.extend([like, like, like])

    where_clause = ""
    if conditions:
        where_clause = "WHERE " + " AND ".join(f"({cond})" for cond in conditions)
    return where_clause, params


def query_events(
    limit: Optional[int] = 50,
    offset: int = 0,
    *,
    event_type: Optional[str] = None,
    route_line: Optional[str] = None,
    track_side: Optional[str] = None,
    has_photo: Optional[bool] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    keyword: Optional[str] = None,
) -> List[ReportEventRecord]:
    where_clause, params = _build_filters(
        event_type=event_type,
        route_line=route_line,
        track_side=track_side,
        has_photo=has_photo,
        start_time=start_time,
        end_time=end_time,
        keyword=keyword,
    )
    sql = f"""
    SELECT *
    FROM reported_events
    {where_clause}
    ORDER BY datetime(created_at) DESC, id DESC
    """
    if limit is not None:
        sql += " LIMIT ? OFFSET ?"
        params.extend([max(1, limit), max(0, offset)])

    conn = get_connection()
    rows = conn.execute(sql, params).fetchall()
    return [ReportEventRecord.from_row(row) for row in rows]


def count_events(
    *,
    event_type: Optional[str] = None,
    route_line: Optional[str] = None,
    track_side: Optional[str] = None,
    has_photo: Optional[bool] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    keyword: Optional[str] = None,
) -> int:
    where_clause, params = _build_filters(
        event_type=event_type,
        route_line=route_line,
        track_side=track_side,
        has_photo=has_photo,
        start_time=start_time,
        end_time=end_time,
        keyword=keyword,
    )
    conn = get_connection()
    row = conn.execute(
        f"SELECT COUNT(1) AS cnt FROM reported_events {where_clause}",
        params,
    ).fetchone()
    return int(row["cnt"] if row else 0)


def list_recent_events(limit: int = 500) -> List[ReportEventRecord]:
    return query_events(limit=min(max(limit, 1), 2000))


def export_events(
    *,
    event_type: Optional[str] = None,
    route_line: Optional[str] = None,
    track_side: Optional[str] = None,
    has_photo: Optional[bool] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    keyword: Optional[str] = None,
) -> List[ReportEventRecord]:
    return query_events(
        limit=None,
        event_type=event_type,
        route_line=route_line,
        track_side=track_side,
        has_photo=has_photo,
        start_time=start_time,
        end_time=end_time,
        keyword=keyword,
    )


def import_events(items: Sequence[Mapping[str, object]]) -> int:
    if not items:
        return 0
    conn = get_connection()
    with conn:
        for item in items:
            _insert_record(conn, item)
    return len(items)
