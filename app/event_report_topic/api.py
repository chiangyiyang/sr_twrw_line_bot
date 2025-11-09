"""Flask blueprint exposing reported event data."""
from __future__ import annotations

import csv
import io
import json
import math
import os
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from flask import Blueprint, Response, abort, jsonify, request

from . import repository
from .models import ReportEventRecord
from ..paths import EVENT_PICTURES_DIR
from ..auth import login_required

api_bp = Blueprint("report_events_api", __name__, url_prefix="/api/events")

_REQUIRED_FIELDS = ("event_type", "route_line", "track_side", "mileage_text")
_CSV_FIELDS = (
    "id",
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
    "created_at",
)


def _parse_int(value: Optional[str], default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value) if value is not None else default
    except (TypeError, ValueError):
        return default
    return max(minimum, min(parsed, maximum))


def _parse_bool(value: Optional[str]) -> Optional[bool]:
    if value is None:
        return None
    lowered = value.strip().lower()
    if lowered in {"1", "true", "yes"}:
        return True
    if lowered in {"0", "false", "no"}:
        return False
    return None


def _parse_filters() -> Dict[str, Optional[str]]:
    return {
        "event_type": request.args.get("event_type") or None,
        "route_line": request.args.get("route_line") or None,
        "track_side": request.args.get("track_side") or None,
        "has_photo": _parse_bool(request.args.get("has_photo")),
        "start_time": request.args.get("start_time") or None,
        "end_time": request.args.get("end_time") or None,
        "keyword": request.args.get("keyword") or None,
    }


def _clean_payload(data: Dict[str, object], *, partial: bool = False) -> Dict[str, object]:
    cleaned: Dict[str, object] = {}
    for key, value in data.items():
        if key not in repository._EVENT_COLUMNS:
            continue
        if key in {"longitude", "latitude", "mileage_meters"}:
            if value in (None, "", "null"):
                cleaned[key] = None
            else:
                try:
                    cleaned[key] = float(value)
                except (TypeError, ValueError):
                    raise ValueError(f"{key} 需要為數值")
        else:
            cleaned[key] = value.strip() if isinstance(value, str) else value

    if not partial:
        for field in _REQUIRED_FIELDS:
            if not cleaned.get(field):
                raise ValueError(f"{field} 為必填欄位")
        cleaned.setdefault("source_type", "admin")
        cleaned.setdefault("source_id", "console")

    return cleaned


def _serialize_items(items):
    return [item.to_dict() for item in items]


@api_bp.get("/")
def list_events():
    limit = _parse_int(request.args.get("limit") or request.args.get("page_size"), 20, 1, 200)
    page = _parse_int(request.args.get("page"), 1, 1, 1_000_000)
    offset = (page - 1) * limit
    filters = _parse_filters()
    items = repository.query_events(limit=limit, offset=offset, **filters)
    total = repository.count_events(**filters)
    pages = math.ceil(total / limit) if limit else 1
    return jsonify(
        {
            "count": len(items),
            "total": total,
            "items": _serialize_items(items),
            "limit": limit,
            "offset": offset,
            "page": page,
            "pages": pages,
            "filters": {k: v for k, v in filters.items() if v is not None},
        }
    )


@api_bp.get("/<int:event_id>")
def get_event(event_id: int):
    event = repository.get_event(event_id)
    if not event:
        abort(404, description="事件不存在")
    return jsonify(event.to_dict())


@api_bp.post("/")
@login_required
def create_event():
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        abort(400, description="請提供 JSON 物件")
    try:
        cleaned = _clean_payload(data)
    except ValueError as exc:
        abort(400, description=str(exc))
    event = repository.create_event(cleaned)
    return jsonify(event.to_dict()), 201


@api_bp.put("/<int:event_id>")
@login_required
def update_event(event_id: int):
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        abort(400, description="請提供 JSON 物件")
    try:
        cleaned = _clean_payload(data, partial=True)
    except ValueError as exc:
        abort(400, description=str(exc))
    updated = repository.update_event(event_id, cleaned)
    if not updated:
        abort(404, description="事件不存在")
    return jsonify(updated.to_dict())


@api_bp.delete("/<int:event_id>")
@login_required
def delete_event(event_id: int):
    event = repository.get_event(event_id)
    if not event:
        abort(404, description="事件不存在")
    _delete_photo_files([event])
    repository.delete_event(event_id)
    return jsonify({"deleted": 1})


@api_bp.post("/bulk-delete")
@login_required
def bulk_delete():
    data = request.get_json(silent=True) or {}
    ids = data.get("ids")
    if not isinstance(ids, list) or not all(isinstance(item, int) for item in ids):
        abort(400, description="ids 需為整數陣列")
    events = repository.get_events_by_ids(ids)
    _delete_photo_files(events)
    deleted = repository.bulk_delete(ids)
    return jsonify({"deleted": deleted})


def _export_json(items: List[dict]) -> Response:
    payload = json.dumps(items, ensure_ascii=False)
    resp = Response(payload, mimetype="application/json; charset=utf-8")
    resp.headers["Content-Disposition"] = "attachment; filename=reported_events.json"
    return resp


def _export_csv(items: List[dict]) -> Response:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=_CSV_FIELDS)
    writer.writeheader()
    for item in items:
        writer.writerow({field: item.get(field) for field in _CSV_FIELDS})
    resp = Response(output.getvalue(), mimetype="text/csv; charset=utf-8")
    resp.headers["Content-Disposition"] = "attachment; filename=reported_events.csv"
    return resp


@api_bp.get("/export")
@login_required
def export_events():
    filters = _parse_filters()
    format_type = (request.args.get("format") or "json").lower()
    items = _serialize_items(repository.export_events(**filters))
    if format_type == "csv":
        return _export_csv(items)
    return _export_json(items)


def _parse_import_items(format_type: str) -> List[dict]:
    if format_type == "csv":
        text = request.get_data(as_text=True)
        if not text:
            abort(400, description="CSV 內容為空")
        reader = csv.DictReader(io.StringIO(text))
        return [row for row in reader]
    data = request.get_json(silent=True)
    if data is None:
        abort(400, description="請提供 JSON 內容或設定 format=csv")
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        items = data.get("items")
        if isinstance(items, list):
            return items
    abort(400, description="JSON 格式須為陣列或含 items 的物件")


@api_bp.post("/import")
@login_required
def import_events():
    format_type = (request.args.get("format") or "").lower()
    if not format_type:
        content_type = request.content_type or ""
        if "csv" in content_type:
            format_type = "csv"
        else:
            format_type = "json"
    raw_items = _parse_import_items(format_type)
    cleaned_items = []
    for item in raw_items:
        try:
            cleaned_items.append(_clean_payload(item))
        except ValueError as exc:
            abort(400, description=f"資料格式錯誤：{exc}")
    inserted = repository.import_events(cleaned_items)
    return jsonify({"imported": inserted})


_PICTURES_DIR = Path(os.getenv("EVENTS_PICTURES_DIR") or EVENT_PICTURES_DIR)


def _photo_path(filename: Optional[str]) -> Optional[Path]:
    if not filename:
        return None
    safe_name = Path(filename).name
    return _PICTURES_DIR / safe_name


def _delete_photo_files(records: Sequence[ReportEventRecord]) -> None:
    for record in records:
        photo_path = _photo_path(getattr(record, "photo_filename", None))
        if not photo_path:
            continue
        try:
            photo_path.unlink(missing_ok=True)
        except TypeError:
            # Python <3.8 missing ok arg
            try:
                if photo_path.exists():
                    photo_path.unlink()
            except OSError:
                continue
