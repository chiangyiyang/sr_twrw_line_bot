"""Shared conversational state for demo topics."""
from typing import Optional


current_topic: Optional[str] = None


def set_topic(topic: Optional[str]) -> None:
    global current_topic
    current_topic = topic


def get_topic() -> Optional[str]:
    return current_topic
