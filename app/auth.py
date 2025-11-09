"""Google Login 驗證與授權輔助工具。"""
from __future__ import annotations

import os
from functools import wraps
from typing import Callable, Dict, Optional, Set, Tuple

from flask import Blueprint, abort, current_app, jsonify, request, session
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


def _split_env_list(value: Optional[str]) -> Set[str]:
    if not value:
        return set()
    return {item.strip().lower() for item in value.split(",") if item.strip()}


def _get_settings() -> Tuple[str, Set[str], Set[str]]:
    client_id = current_app.config.get("GOOGLE_CLIENT_ID") or os.getenv("GOOGLE_CLIENT_ID") or ""
    allowed_emails = current_app.config.get("GOOGLE_ALLOWED_EMAILS")
    allowed_domains = current_app.config.get("GOOGLE_ALLOWED_DOMAINS")
    if not isinstance(allowed_emails, set):
        allowed_emails = _split_env_list(os.getenv("GOOGLE_ALLOWED_EMAILS"))
    if not isinstance(allowed_domains, set):
        allowed_domains = _split_env_list(os.getenv("GOOGLE_ALLOWED_DOMAINS"))
    return client_id, allowed_emails, allowed_domains


def _is_authorized(email: Optional[str], allowed_emails: Set[str], allowed_domains: Set[str]) -> bool:
    if not email:
        return False
    lowered = email.lower()
    if allowed_emails and lowered in allowed_emails:
        return True
    if allowed_domains:
        domain = lowered.split("@")[-1]
        if domain in allowed_domains:
            return True
    return not (allowed_emails or allowed_domains)


def _build_user_payload(token_info: Dict[str, object]) -> Dict[str, object]:
    return {
        "email": token_info.get("email"),
        "name": token_info.get("name"),
        "picture": token_info.get("picture"),
        "sub": token_info.get("sub"),
    }


def login_required(func: Callable):
    """保護僅授權使用者可使用的端點。"""

    @wraps(func)
    def wrapper(*args, **kwargs):
        if not session.get("user"):
            abort(401, description="請先登入")
        return func(*args, **kwargs)

    return wrapper


@auth_bp.get("/config")
def auth_config():
    client_id, _, _ = _get_settings()
    if not client_id:
        abort(500, description="尚未設定 GOOGLE_CLIENT_ID")
    return jsonify({"google_client_id": client_id})


@auth_bp.get("/status")
def auth_status():
    user = session.get("user")
    return jsonify({"authenticated": bool(user), "user": user})


@auth_bp.post("/login")
def auth_login():
    client_id, allowed_emails, allowed_domains = _get_settings()
    if not client_id:
        abort(500, description="尚未設定 GOOGLE_CLIENT_ID")

    data = request.get_json(silent=True) or {}
    credential = data.get("credential")
    if not credential:
        abort(400, description="缺少 credential")

    try:
        token_info = id_token.verify_oauth2_token(
            credential,
            google_requests.Request(),
            audience=client_id,
        )
    except ValueError as exc:
        abort(401, description=f"Google 驗證失敗：{exc}")

    if not _is_authorized(token_info.get("email"), allowed_emails, allowed_domains):
        abort(403, description="無瀏覽權限")

    session["user"] = _build_user_payload(token_info)
    return jsonify({"authenticated": True, "user": session["user"]})


@auth_bp.post("/logout")
def auth_logout():
    session.pop("user", None)
    return jsonify({"authenticated": False})
