"""Flask blueprint exposing rainfall data."""
from __future__ import annotations

from flask import Blueprint, abort, jsonify, request

from . import repository
from .models import StationObservation

api_bp = Blueprint("rainfall_api", __name__, url_prefix="/api/rainfall")


def _parse_int(value: str, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(parsed, maximum))


def _observations_payload(items: list[StationObservation], **meta):
    payload = {
        "count": len(items),
        "items": [item.to_dict() for item in items],
        "updated_at": repository.get_latest_obs_time(),
    }
    if meta:
        payload["meta"] = meta
    return jsonify(payload)


@api_bp.get("/latest")
def get_latest():
    limit = _parse_int(request.args.get("limit"), default=100, minimum=1, maximum=500)
    items = repository.get_recent_observations(limit)
    return _observations_payload(items)


@api_bp.get("/search")
def search():
    query_type = (request.args.get("type") or "").lower()
    limit = _parse_int(request.args.get("limit"), default=3, minimum=1, maximum=20)

    if query_type == "coordinate":
        lon = request.args.get("lon")
        lat = request.args.get("lat")
        if lon is None or lat is None:
            abort(400, description="請提供 lon 與 lat 參數。")
        try:
            lon_val = float(lon)
            lat_val = float(lat)
        except ValueError:
            abort(400, description="lon/lat 需為數值。")
        items = repository.search_nearest_by_coordinate(lon_val, lat_val, limit)
        return _observations_payload(items, query={"type": "coordinate", "lon": lon_val, "lat": lat_val})

    if query_type == "station":
        keyword = (request.args.get("keyword") or "").strip()
        if not keyword:
            abort(400, description="請提供 keyword 參數。")
        items = repository.search_by_station_name(keyword, limit)
        return _observations_payload(items, query={"type": "station", "keyword": keyword})

    if query_type == "district":
        city = (request.args.get("city") or "").strip()
        if not city:
            abort(400, description="請提供 city 參數。")
        town = (request.args.get("town") or "").strip() or None
        items = repository.search_by_district(city, town, 200)
        return _observations_payload(items, query={"type": "district", "city": city, "town": town})

    abort(400, description="未知的查詢 type 參數。")


@api_bp.get("/stations/<station_id>")
def get_station(station_id: str):
    item = repository.get_station_observation(station_id)
    if not item:
        abort(404, description="找不到測站資料。")
    return _observations_payload([item])
