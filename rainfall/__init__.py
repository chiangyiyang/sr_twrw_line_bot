"""Rainfall data module bootstrap helpers."""
from __future__ import annotations

import os
from flask import Flask

from .api import api_bp
from .poller import start_background_poller


def init_app(app: Flask) -> None:
    """Register rainfall blueprints and background jobs with the Flask app."""
    app.register_blueprint(api_bp)
    if app.config.get("TESTING"):
        return
    if os.getenv("DISABLE_RAINFALL_POLLER") == "1":
        return
    start_background_poller()


def get_public_page_url() -> str:
    """Return the public URL that hosts rainfall.html."""
    explicit_url = os.getenv("RAINFALL_PAGE_URL")
    if explicit_url:
        return explicit_url

    base_url = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
    if base_url:
        return f"{base_url}/rainfall.html"

    host = os.getenv("PUBLIC_HOST") or os.getenv("HOST", "localhost")
    port = os.getenv("PUBLIC_PORT") or os.getenv("PORT", "8000")
    port_text = f":{port}" if port not in ("80", "443") else ""
    scheme = "https" if port == "443" else "http"
    return f"{scheme}://{host}{port_text}/rainfall.html"


__all__ = ["init_app", "get_public_page_url"]
