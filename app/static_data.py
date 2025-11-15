import os

from flask import abort, Blueprint, send_from_directory

from .paths import DATA_DIR, EVENT_PICTURES_DIR


static_data_bp = Blueprint("static_data", __name__)


@static_data_bp.route("/cctv_data.json")
def cctv_data():
    return send_from_directory(
        str(DATA_DIR),
        "cctv_data.json",
        max_age=60,
        conditional=True,
    )


def _normalize_picture_path(filename: str) -> str:
    normalized = os.path.normpath(filename)
    if normalized.startswith("..") or normalized.startswith(os.sep):
        abort(404)
    return normalized


@static_data_bp.route("/events/pictures/<path:filename>")
def event_picture(filename: str):
    safe_filename = _normalize_picture_path(filename)
    return send_from_directory(
        str(EVENT_PICTURES_DIR),
        safe_filename,
        max_age=300,
        conditional=True,
    )
