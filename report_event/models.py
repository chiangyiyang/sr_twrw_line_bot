"""Dataclasses for event report records."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class ReportEventRecord:
    id: Optional[int]
    event_type: str
    route_line: str
    track_side: str
    mileage_text: str
    mileage_meters: Optional[float]
    photo_filename: Optional[str]
    longitude: Optional[float]
    latitude: Optional[float]
    location_title: Optional[str]
    location_address: Optional[str]
    source_type: Optional[str]
    source_id: Optional[str]
    created_at: Optional[str] = None

    def to_dict(self) -> Dict[str, object]:
        return {
            "id": self.id,
            "event_type": self.event_type,
            "route_line": self.route_line,
            "track_side": self.track_side,
            "mileage_text": self.mileage_text,
            "mileage_meters": self.mileage_meters,
            "photo_filename": self.photo_filename,
            "longitude": self.longitude,
            "latitude": self.latitude,
            "location_title": self.location_title,
            "location_address": self.location_address,
            "source_type": self.source_type,
            "source_id": self.source_id,
            "created_at": self.created_at,
        }

    @classmethod
    def from_row(cls, row) -> "ReportEventRecord":
        return cls(
            id=row["id"],
            event_type=row["event_type"],
            route_line=row["route_line"],
            track_side=row["track_side"],
            mileage_text=row["mileage_text"],
            mileage_meters=row["mileage_meters"],
            photo_filename=row["photo_filename"],
            longitude=row["longitude"],
            latitude=row["latitude"],
            location_title=row["location_title"],
            location_address=row["location_address"],
            source_type=row["source_type"],
            source_id=row["source_id"],
            created_at=row["created_at"],
        )
