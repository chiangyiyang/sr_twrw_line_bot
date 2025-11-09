"""Flask blueprint exposing reported event data."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from . import repository

api_bp = Blueprint("report_events_api", __name__, url_prefix="/api/events")


def _parse_int(value: str | None, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value) if value is not None else default
    except ValueError:
        return default
    return max(minimum, min(parsed, maximum))


@api_bp.get("/")
def list_events():
    limit = _parse_int(request.args.get("limit"), default=500, minimum=1, maximum=2000)
    items = repository.list_recent_events(limit)
    return jsonify(
        {
            "count": len(items),
            "items": [item.to_dict() for item in items],
        }
    )
