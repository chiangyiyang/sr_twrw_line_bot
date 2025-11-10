"""Utilities for handling event photo filenames."""
from __future__ import annotations

import json
import re
from typing import Iterable, List, Optional, Sequence, Union

PhotoInput = Union[str, Sequence[str], None]


def _clean_item(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    return candidate or None


def parse_photo_field(value: PhotoInput) -> List[str]:
    """Normalize stored photo metadata into a list of filenames/URLs."""
    if value is None:
        return []

    if isinstance(value, (list, tuple, set)):
        result = []
        for item in value:
            cleaned = _clean_item(item) if isinstance(item, str) else None
            if cleaned:
                result.append(cleaned)
        return result

    if not isinstance(value, str):
        return []

    text = value.strip()
    if not text:
        return []

    if text.startswith("["):
        try:
            decoded = json.loads(text)
        except json.JSONDecodeError:
            pass
        else:
            if isinstance(decoded, list):
                return [
                    item.strip()
                    for item in decoded
                    if isinstance(item, str) and item.strip()
                ]
            if isinstance(decoded, str) and decoded.strip():
                return [decoded.strip()]

    if any(sep in text for sep in ("\n", ",")):
        parts = [segment.strip() for segment in re.split(r"[\n,]+", text)]
        return [segment for segment in parts if segment]

    return [text]


def serialize_photo_field(items: Iterable[str]) -> Optional[str]:
    """Serialize a list of filenames into the database format."""
    cleaned = []
    for item in items:
        cleaned_item = _clean_item(item)
        if cleaned_item:
            cleaned.append(cleaned_item)

    if not cleaned:
        return None
    if len(cleaned) == 1:
        return cleaned[0]
    return json.dumps(cleaned, ensure_ascii=False)
