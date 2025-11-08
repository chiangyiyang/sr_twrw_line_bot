"""Background poller that stores rainfall observations locally."""
from __future__ import annotations

import argparse
import json
import os
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Tuple

from dotenv import load_dotenv

from . import repository

load_dotenv()

DATASET_ID = "O-A0002-001"
DEFAULT_API_URL = "https://opendata.cwa.gov.tw/api/v1/rest/datastore"
_THREAD: Optional[threading.Thread] = None
_THREAD_LOCK = threading.Lock()


def _get_api_endpoint() -> str:
    base_url = os.getenv("CWA_API_BASE", DEFAULT_API_URL).rstrip("/")
    return f"{base_url}/{DATASET_ID}"


def _to_dict(entries: Optional[Iterable[Dict]], key: str, value_key: str) -> Dict[str, Optional[str]]:
    result: Dict[str, Optional[str]] = {}
    if not entries:
        return result
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        dict_key = entry.get(key)
        value = entry.get(value_key)
        if isinstance(value, dict) and "value" in value:
            value = value.get("value")
        if dict_key:
            result[str(dict_key)] = value
    return result


def _to_float(value: Optional[object]) -> Optional[float]:
    if value in (None, "", "-"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract_coordinates(loc: Dict) -> Optional[Tuple[float, float]]:
    geo_info = loc.get("GeoInfo") or {}
    coords = geo_info.get("Coordinates")
    candidates = []
    if isinstance(coords, list):
        for item in coords:
            if not isinstance(item, dict):
                continue
            name = (item.get("CoordinateName") or "").upper()
            if name == "WGS84":
                candidates.insert(0, item)
            else:
                candidates.append(item)

    for candidate in candidates:
        lat = candidate.get("StationLatitude") or candidate.get("lat") or candidate.get("latitude")
        lon = candidate.get("StationLongitude") or candidate.get("lon") or candidate.get("longitude")
        if isinstance(lat, dict):
            lat = lat.get("value")
        if isinstance(lon, dict):
            lon = lon.get("value")
        lat_val = _to_float(lat)
        lon_val = _to_float(lon)
        if lat_val is not None and lon_val is not None:
            return lon_val, lat_val

    lat = loc.get("lat") or loc.get("latitude") or geo_info.get("StationLatitude")
    lon = loc.get("lon") or loc.get("longitude") or geo_info.get("StationLongitude")
    if isinstance(lat, dict):
        lat = lat.get("value")
    if isinstance(lon, dict):
        lon = lon.get("value")
    lat_val = _to_float(lat or loc.get("StationLatitude"))
    lon_val = _to_float(lon or loc.get("StationLongitude"))

    if lat_val is None or lon_val is None:
        return None
    return lon_val, lat_val


def _extract_obs_time(loc: Dict) -> Optional[str]:
    obs_time = loc.get("time", {}).get("obsTime")
    if obs_time:
        return obs_time
    obs_time = loc.get("ObsTime", {}).get("DateTime")
    if obs_time:
        return obs_time
    obs_time = loc.get("ObsTime")
    if isinstance(obs_time, dict):
        return obs_time.get("DateTime")
    return obs_time


def _parse_location_entry(loc: Dict) -> Optional[Dict[str, object]]:
    station_id = loc.get("stationId") or loc.get("StationId")
    station_name = loc.get("locationName") or loc.get("StationName")
    if not station_id or not station_name:
        return None

    obs_time = _extract_obs_time(loc)
    coords = _extract_coordinates(loc)
    if not obs_time or coords is None:
        return None

    longitude, latitude = coords
    param_dict = _to_dict(loc.get("parameter"), "parameterName", "parameterValue")
    weather_dict = _to_dict(loc.get("weatherElement"), "elementName", "elementValue")
    rainfall_element = loc.get("RainfallElement") or {}
    geo_info = loc.get("GeoInfo") or {}

    city = param_dict.get("CITY") or geo_info.get("CountyName")
    town = param_dict.get("TOWN") or geo_info.get("TownName")
    attribute = param_dict.get("ATTRIBUTE") or loc.get("Maintainer") or geo_info.get("Maintainer")
    elevation = _to_float(weather_dict.get("ELEV") or geo_info.get("StationAltitude"))
    if elevation is None:
        elevation = _to_float(loc.get("StationAltitude"))

    min_10 = _to_float(weather_dict.get("MIN_10") or rainfall_element.get("Past10Min", {}).get("Precipitation"))
    hour_1 = _to_float(weather_dict.get("RAIN") or rainfall_element.get("Past1hr", {}).get("Precipitation") or rainfall_element.get("Past1Hr", {}).get("Precipitation"))
    hour_3 = _to_float(weather_dict.get("HOUR_3") or rainfall_element.get("Past3hr", {}).get("Precipitation") or rainfall_element.get("Past3Hr", {}).get("Precipitation"))
    hour_6 = _to_float(weather_dict.get("HOUR_6") or rainfall_element.get("Past6hr", {}).get("Precipitation") or rainfall_element.get("Past6Hr", {}).get("Precipitation"))
    hour_12 = _to_float(weather_dict.get("HOUR_12") or rainfall_element.get("Past12hr", {}).get("Precipitation"))
    hour_24 = _to_float(weather_dict.get("HOUR_24") or rainfall_element.get("Past24hr", {}).get("Precipitation"))

    return {
        "station_id": station_id,
        "station_name": station_name,
        "city": city,
        "town": town,
        "attribute": attribute,
        "latitude": latitude,
        "longitude": longitude,
        "elevation": elevation,
        "obs_time": obs_time,
        "min_10": min_10,
        "hour_1": hour_1,
        "hour_3": hour_3,
        "hour_6": hour_6,
        "hour_12": hour_12,
        "hour_24": hour_24,
    }


def fetch_remote_data(api_key: str) -> List[Dict[str, object]]:
    endpoint = _get_api_endpoint()
    url = f"{endpoint}?Authorization={api_key}"
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "sr-twrw-line-bot/1.0",
            "Accept": "application/json",
        },
    )

    with urllib.request.urlopen(request, timeout=60) as response:
        payload = response.read()
        encoding = response.headers.get_content_charset() or "utf-8"
        data = json.loads(payload.decode(encoding))

    records = data.get("records") or {}
    locations = records.get("location") or records.get("Station") or []

    parsed: List[Dict[str, object]] = []
    for loc in locations:
        if not isinstance(loc, dict):
            continue
        item = _parse_location_entry(loc)
        if item:
            parsed.append(item)
    return parsed


def run_once(verbose: bool = True) -> bool:
    api_key = os.getenv("CWA_API_KEY")
    if not api_key:
        if verbose:
            print("WARN: CWA_API_KEY 未設定，無法下載雨量資料。")
        return False

    try:
        items = fetch_remote_data(api_key)
    except urllib.error.URLError as exc:
        if verbose:
            print(f"ERROR: 無法下載雨量資料 - {exc}")
        return False
    except json.JSONDecodeError as exc:
        if verbose:
            print(f"ERROR: 解析雨量資料失敗 - {exc}")
        return False

    if not items:
        if verbose:
            print("WARN: API 回傳空資料。")
        return False

    repository.upsert_observations(items)
    timestamp = datetime.now(timezone.utc).isoformat()
    repository.set_last_success_at(timestamp)
    if verbose:
        print(f"INFO: 已更新 {len(items)} 筆雨量資料。")
    return True


def _polling_loop(interval_seconds: int) -> None:
    wait_seconds = 0
    while True:
        if wait_seconds:
            time.sleep(wait_seconds)
        success = run_once(verbose=False)
        wait_seconds = interval_seconds if success else min(interval_seconds, 120)


def start_background_poller() -> None:
    interval = int(os.getenv("RAINFALL_POLL_INTERVAL", "600"))
    global _THREAD
    with _THREAD_LOCK:
        if _THREAD and _THREAD.is_alive():
            return
        thread = threading.Thread(
            target=_polling_loop,
            name="rainfall-poller",
            args=(interval,),
            daemon=True,
        )
        thread.start()
        _THREAD = thread


def main() -> None:
    parser = argparse.ArgumentParser(description="Rainfall poller")
    parser.add_argument("--once", action="store_true", help="只執行一次抓取")
    args = parser.parse_args()

    if args.once:
        run_once(verbose=True)
    else:
        start_background_poller()
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            print("Rainfall poller stopped.")


if __name__ == "__main__":
    main()
