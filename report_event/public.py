"""Helpers for exposing event map URLs."""
from __future__ import annotations

import os


def get_public_page_url() -> str:
    explicit_url = os.getenv("EVENTS_PAGE_URL")
    if explicit_url:
        return explicit_url

    base_url = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
    if base_url:
        return f"{base_url}/events.html"

    host = os.getenv("PUBLIC_HOST") or os.getenv("HOST", "localhost")
    port = os.getenv("PUBLIC_PORT") or os.getenv("PORT", "8000")
    port_text = f":{port}" if port not in ("80", "443") else ""
    scheme = "https" if port == "443" else "http"
    return f"{scheme}://{host}{port_text}/events.html"


__all__ = ["get_public_page_url"]
