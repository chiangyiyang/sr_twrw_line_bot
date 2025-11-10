"""Persistence helpers for audit log records."""
from __future__ import annotations

import json
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from .database import get_connection

_LOG_COLUMNS = (
    "action_type",
    "channel",
    "actor_type",
    "actor_id",
    "actor_name",
    "ip_address",
    "resource_type",
    "resource_id",
    "status",
    "message",
    "details",
)


def insert_log(payload: Mapping[str, object]) -> int:
    conn = get_connection()
    placeholders = ", ".join("?" for _ in _LOG_COLUMNS)
    column_sql = ", ".join(_LOG_COLUMNS)
    values = [payload.get(column) for column in _LOG_COLUMNS]
    with conn:
        cursor = conn.execute(
            f"""
            INSERT INTO audit_logs ({column_sql})
            VALUES ({placeholders})
            """,
            values,
        )
    return int(cursor.lastrowid)


def _row_to_dict(row) -> Dict[str, object]:
    details_raw = row["details"]
    parsed_details: Optional[object] = None
    if details_raw:
        try:
            parsed_details = json.loads(details_raw)
        except (TypeError, ValueError):
            parsed_details = details_raw
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "action_type": row["action_type"],
        "channel": row["channel"],
        "actor_type": row["actor_type"],
        "actor_id": row["actor_id"],
        "actor_name": row["actor_name"],
        "ip_address": row["ip_address"],
        "resource_type": row["resource_type"],
        "resource_id": row["resource_id"],
        "status": row["status"],
        "message": row["message"],
        "details": parsed_details,
        "details_raw": details_raw,
    }


def _build_filters(
    *,
    action_type: Optional[str] = None,
    actor_id: Optional[str] = None,
    status: Optional[str] = None,
    channel: Optional[str] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    keyword: Optional[str] = None,
) -> Tuple[str, List[object]]:
    conditions: List[str] = []
    params: List[object] = []
    if action_type:
        conditions.append("action_type = ?")
        params.append(action_type)
    if actor_id:
        conditions.append("actor_id = ?")
        params.append(actor_id)
    if status:
        conditions.append("status = ?")
        params.append(status.lower())
    if channel:
        conditions.append("channel = ?")
        params.append(channel)
    if resource_type:
        conditions.append("resource_type = ?")
        params.append(resource_type)
    if resource_id:
        conditions.append("resource_id = ?")
        params.append(resource_id)
    if start_time:
        conditions.append("datetime(created_at) >= datetime(?)")
        params.append(start_time)
    if end_time:
        conditions.append("datetime(created_at) <= datetime(?)")
        params.append(end_time)
    if keyword:
        conditions.append("(message LIKE ? OR details LIKE ?)")
        like = f"%{keyword}%"
        params.extend([like, like])

    where_clause = ""
    if conditions:
        where_clause = "WHERE " + " AND ".join(f"({cond})" for cond in conditions)
    return where_clause, params


def query_logs(
    limit: Optional[int],
    offset: int,
    **filters,
) -> List[Dict[str, object]]:
    where_clause, params = _build_filters(**filters)
    sql = f"""
    SELECT *
    FROM audit_logs
    {where_clause}
    ORDER BY datetime(created_at) DESC, id DESC
    """
    if limit is not None:
        sql += " LIMIT ? OFFSET ?"
        params.extend([max(1, limit), max(0, offset)])

    conn = get_connection()
    rows = conn.execute(sql, params).fetchall()
    return [_row_to_dict(row) for row in rows]


def count_logs(**filters) -> int:
    where_clause, params = _build_filters(**filters)
    conn = get_connection()
    row = conn.execute(f"SELECT COUNT(1) AS cnt FROM audit_logs {where_clause}", params).fetchone()
    return int(row["cnt"] if row else 0)


def export_logs(**filters) -> List[Dict[str, object]]:
    return query_logs(limit=None, offset=0, **filters)


def delete_logs(before_time: Optional[str] = None) -> int:
    conn = get_connection()
    if before_time:
        sql = "DELETE FROM audit_logs WHERE datetime(created_at) <= datetime(?)"
        params = (before_time,)
    else:
        sql = "DELETE FROM audit_logs"
        params = ()
    with conn:
        cursor = conn.execute(sql, params)
    return cursor.rowcount


__all__ = ["insert_log", "query_logs", "count_logs", "export_logs", "delete_logs"]
