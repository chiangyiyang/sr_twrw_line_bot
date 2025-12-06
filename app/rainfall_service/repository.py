"""Data access helpers for rainfall observations."""
from __future__ import annotations

import math
from typing import Iterable, List, Mapping, Optional, Sequence, Tuple

from .database import get_connection
from .models import StationObservation

_BASE_SELECT = """
SELECT
    s.station_id,
    s.station_name,
    s.city,
    s.town,
    s.attribute,
    s.latitude,
    s.longitude,
    s.elevation,
    o.obs_time,
    o.min_10,
    o.hour_1,
    o.hour_3,
    o.hour_6,
    o.hour_12,
    o.hour_24
FROM stations AS s
JOIN observations AS o ON o.station_id = s.station_id
JOIN (
    SELECT station_id, MAX(obs_time) AS latest_obs_time
    FROM observations
    GROUP BY station_id
) AS latest ON latest.station_id = o.station_id AND latest.latest_obs_time = o.obs_time
"""


def _row_to_observation(row) -> StationObservation:
    return StationObservation(
        station_id=row["station_id"],
        station_name=row["station_name"],
        city=row["city"],
        town=row["town"],
        attribute=row["attribute"],
        latitude=row["latitude"],
        longitude=row["longitude"],
        elevation=row["elevation"],
        obs_time=row["obs_time"],
        min_10=row["min_10"],
        hour_1=row["hour_1"],
        hour_3=row["hour_3"],
        hour_6=row["hour_6"],
        hour_12=row["hour_12"],
        hour_24=row["hour_24"],
    )


def upsert_observations(items: Sequence[Mapping[str, object]]) -> int:
    """Insert/Update station meta and observation values."""
    if not items:
        return 0

    conn = get_connection()
    with conn:
        for item in items:
            conn.execute(
                """
                INSERT INTO stations (
                    station_id, station_name, city, town, attribute,
                    latitude, longitude, elevation
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(station_id) DO UPDATE SET
                    station_name=excluded.station_name,
                    city=excluded.city,
                    town=excluded.town,
                    attribute=excluded.attribute,
                    latitude=excluded.latitude,
                    longitude=excluded.longitude,
                    elevation=excluded.elevation
                """,
                (
                    item["station_id"],
                    item["station_name"],
                    item.get("city"),
                    item.get("town"),
                    item.get("attribute"),
                    item["latitude"],
                    item["longitude"],
                    item.get("elevation"),
                ),
            )
            conn.execute(
                """
                INSERT INTO observations (
                    station_id, obs_time, min_10, hour_1, hour_3,
                    hour_6, hour_12, hour_24, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(station_id, obs_time) DO UPDATE SET
                    min_10=excluded.min_10,
                    hour_1=excluded.hour_1,
                    hour_3=excluded.hour_3,
                    hour_6=excluded.hour_6,
                    hour_12=excluded.hour_12,
                    hour_24=excluded.hour_24,
                    created_at=excluded.created_at
                """,
                (
                    item["station_id"],
                    item["obs_time"],
                    item.get("min_10"),
                    item.get("hour_1"),
                    item.get("hour_3"),
                    item.get("hour_6"),
                    item.get("hour_12"),
                    item.get("hour_24"),
                ),
            )

    return len(items)


def set_last_success_at(timestamp: str) -> None:
    conn = get_connection()
    with conn:
        conn.execute(
            """
            INSERT INTO poller_state (id, last_success_at)
            VALUES (1, ?)
            ON CONFLICT(id) DO UPDATE SET last_success_at=excluded.last_success_at
            """,
            (timestamp,),
        )


def get_last_success_at() -> Optional[str]:
    conn = get_connection()
    row = conn.execute("SELECT last_success_at FROM poller_state WHERE id = 1").fetchone()
    return row["last_success_at"] if row else None


def delete_observations_older_than_days(days: int) -> int:
    """Delete observations older than the specified number of days.
    
    Args:
        days: Number of days to retain (observations older than this will be deleted)
        
    Returns:
        Number of records deleted
    """
    conn = get_connection()
    with conn:
        cursor = conn.execute(
            "DELETE FROM observations WHERE obs_time < datetime('now', ? || ' day')",
            (f"-{days}",),
        )
        return cursor.rowcount


def get_latest_obs_time() -> Optional[str]:
    conn = get_connection()
    row = conn.execute("SELECT MAX(obs_time) AS obs_time FROM observations").fetchone()
    return row["obs_time"] if row and row["obs_time"] else None


def get_recent_observations(limit: int = 50) -> List[StationObservation]:
    limit = max(1, min(limit, 500))
    query = f"{_BASE_SELECT} ORDER BY o.obs_time DESC LIMIT ?"
    conn = get_connection()
    rows = conn.execute(query, (limit,)).fetchall()
    return [_row_to_observation(row) for row in rows]


def get_station_observation(station_id: str) -> Optional[StationObservation]:
    conn = get_connection()
    row = conn.execute(
        f"{_BASE_SELECT} WHERE s.station_id = ? LIMIT 1",
        (station_id,),
    ).fetchone()
    return _row_to_observation(row) if row else None


def search_by_station_name(keyword: str, limit: int = 5) -> List[StationObservation]:
    keyword = (keyword or "").strip()
    if not keyword:
        return []
    like = f"%{keyword}%"
    conn = get_connection()
    rows = conn.execute(
        f"""{_BASE_SELECT}
        WHERE s.station_name LIKE ? OR s.station_id LIKE ?
        ORDER BY s.station_name
        LIMIT ?
        """,
        (like, like, max(1, min(limit, 20))),
    ).fetchall()
    return [_row_to_observation(row) for row in rows]


def search_by_district(city: str, town: Optional[str] = None, limit: int = 50) -> List[StationObservation]:
    city = (city or "").strip()
    town = (town or "").strip()
    if not city:
        return []

    params: List[str] = [city]
    where = "WHERE s.city = ?"
    if town:
        where += " AND s.town LIKE ?"
        params.append(f"%{town}%")

    conn = get_connection()
    rows = conn.execute(
        f"""{_BASE_SELECT}
        {where}
        ORDER BY s.town, s.station_name
        LIMIT ?
        """,
        (*params, max(1, min(limit, 200))),
    ).fetchall()
    return [_row_to_observation(row) for row in rows]


def search_nearest_by_coordinate(longitude: float, latitude: float, limit: int = 3) -> List[StationObservation]:
    """Return the closest stations by great-circle distance."""
    limit = max(1, min(limit, 10))
    conn = get_connection()
    # Fetch extra rows to ensure accurate ordering after precise distance calc.
    candidate_limit = min(limit * 5, 100)
    rows = conn.execute(
        f"""{_BASE_SELECT}
        ORDER BY ABS(s.latitude - ?) + ABS(s.longitude - ?)
        LIMIT ?
        """,
        (latitude, longitude, candidate_limit),
    ).fetchall()

    def _distance(row) -> float:
        return _haversine(
            latitude,
            longitude,
            row["latitude"],
            row["longitude"],
        )

    sorted_rows = sorted(rows, key=_distance)
    return [_row_to_observation(row) for row in sorted_rows[:limit]]


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6_371_000.0
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    dlat = lat2_rad - lat1_rad
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return radius * c


__all__ = [
    "StationObservation",
    "get_latest_obs_time",
    "get_recent_observations",
    "get_station_observation",
    "search_by_station_name",
    "search_by_district",
    "search_nearest_by_coordinate",
    "upsert_observations",
    "set_last_success_at",
    "get_last_success_at",
    "delete_observations_older_than_days",
]
