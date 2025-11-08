"""Shared rainfall data models."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class StationObservation:
    station_id: str
    station_name: str
    obs_time: str
    city: Optional[str]
    town: Optional[str]
    attribute: Optional[str]
    latitude: float
    longitude: float
    elevation: Optional[float]
    min_10: Optional[float]
    hour_1: Optional[float]
    hour_3: Optional[float]
    hour_6: Optional[float]
    hour_12: Optional[float]
    hour_24: Optional[float]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "stationId": self.station_id,
            "stationName": self.station_name,
            "city": self.city,
            "town": self.town,
            "attribute": self.attribute,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "elevation": self.elevation,
            "obsTime": self.obs_time,
            "rainfall": {
                "min10": self.min_10,
                "hour1": self.hour_1,
                "hour3": self.hour_3,
                "hour6": self.hour_6,
                "hour12": self.hour_12,
                "hour24": self.hour_24,
            },
        }


__all__ = ["StationObservation"]
