"""Central location for resolving project paths."""
from __future__ import annotations

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = BASE_DIR / "src"
STATIC_DIR = BASE_DIR / "static"
DATA_DIR = BASE_DIR / "data"
STORAGE_DIR = BASE_DIR / "storage"

EVENT_PICTURES_DIR = STORAGE_DIR / "events" / "pictures"
RAILWAY_DATA_PATH = DATA_DIR / "railway_data.json"
CCTV_DATA_PATH = DATA_DIR / "cctv_data.json"
RAINFALL_DB_PATH = DATA_DIR / "rainfall.db"
EVENTS_DB_PATH = DATA_DIR / "report_events.db"
