"""Per-source conversational topic tracking."""
from __future__ import annotations

from typing import Dict, Optional

_topics: Dict[str, Optional[str]] = {}


def set_topic(source_id: str, topic: Optional[str]) -> None:
    """Record current topic for a given source (user/group/room)."""
    if topic is None:
        _topics.pop(source_id, None)
    else:
        _topics[source_id] = topic


def get_topic(source_id: str) -> Optional[str]:
    """Return the active topic for a source, if any."""
    return _topics.get(source_id)
