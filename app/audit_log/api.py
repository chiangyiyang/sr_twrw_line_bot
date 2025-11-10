"""REST API for system audit logs."""
from __future__ import annotations

import csv
import io
import json
from typing import Dict

from flask import Blueprint, Response, abort, jsonify, request

from ..auth import login_required
from . import repository, record_action as audit_record_action

api_bp = Blueprint("audit_log_api", __name__, url_prefix="/api/audit-logs")

_CSV_FIELDS = (
    "id",
    "created_at",
    "action_type",
    "status",
    "channel",
    "actor_type",
    "actor_id",
    "actor_name",
    "ip_address",
    "resource_type",
    "resource_id",
    "message",
    "details",
)


def _parse_int(value: str, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(parsed, maximum))


def _extract_filters() -> Dict[str, str]:
    return {
        "action_type": (request.args.get("action_type") or "").strip() or None,
        "actor_id": (request.args.get("actor_id") or "").strip() or None,
        "status": (request.args.get("status") or "").strip() or None,
        "channel": (request.args.get("channel") or "").strip() or None,
        "resource_type": (request.args.get("resource_type") or "").strip() or None,
        "resource_id": (request.args.get("resource_id") or "").strip() or None,
        "start_time": (request.args.get("start_time") or "").strip() or None,
        "end_time": (request.args.get("end_time") or "").strip() or None,
        "keyword": (request.args.get("keyword") or "").strip() or None,
    }


@api_bp.get("/")
@login_required
def list_logs():
    limit = _parse_int(request.args.get("limit") or 20, 20, 1, 200)
    page = _parse_int(request.args.get("page") or 1, 1, 1, 1_000_000)
    offset = (page - 1) * limit
    filters = _extract_filters()
    items = repository.query_logs(limit=limit, offset=offset, **filters)
    total = repository.count_logs(**filters)
    pages = max(1, (total + limit - 1) // limit)
    return jsonify(
        {
            "count": len(items),
            "items": items,
            "limit": limit,
            "offset": offset,
            "page": page,
            "pages": pages,
            "total": total,
        }
    )


def _export_csv(items) -> Response:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(_CSV_FIELDS)
    for item in items:
        details = item.get("details")
        if details is not None and not isinstance(details, str):
            try:
                details = json.dumps(details, ensure_ascii=False)
            except (TypeError, ValueError):
                details = str(details)
        writer.writerow(
            [
                item.get("id"),
                item.get("created_at"),
                item.get("action_type"),
                item.get("status"),
                item.get("channel"),
                item.get("actor_type"),
                item.get("actor_id"),
                item.get("actor_name"),
                item.get("ip_address"),
                item.get("resource_type"),
                item.get("resource_id"),
                item.get("message"),
                details,
            ]
        )
    response = Response(buffer.getvalue(), mimetype="text/csv; charset=utf-8")
    response.headers["Content-Disposition"] = "attachment; filename=audit_logs.csv"
    return response


@api_bp.get("/export")
@login_required
def export_logs():
    format_type = (request.args.get("format") or "csv").lower()
    filters = _extract_filters()
    items = repository.export_logs(**filters)
    if format_type == "json":
        return jsonify({"items": items, "total": len(items)})
    return _export_csv(items)


@api_bp.post("/clear")
@login_required
def clear_logs():
    data = request.get_json(silent=True) or {}
    confirm = (data.get("confirm") or "").strip().upper()
    if confirm != "DELETE":
        abort(400, description="請輸入 DELETE 以確認刪除")
    before_time = (data.get("before_time") or "").strip() or None
    deleted = repository.delete_logs(before_time=before_time)
    audit_record_action(
        "audit_logs.clear",
        channel="http",
        resource_type="audit_logs",
        resource_id="clear",
        metadata={"deleted": deleted, "before_time": before_time},
    )
    return jsonify({"deleted": deleted})


__all__ = ["api_bp"]
