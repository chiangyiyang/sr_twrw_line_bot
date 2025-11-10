"""Google Login 驗證與後台權限控制。"""
from __future__ import annotations

import os
from functools import wraps
from typing import Callable, Dict, Optional, Set, Tuple

from flask import Blueprint, abort, current_app, jsonify, request, session
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from .audit_log import record_action as audit_record_action

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


def _request_ip() -> Optional[str]:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip() or None
    return request.remote_addr


def _build_actor(email: Optional[str], name: Optional[str], sub: Optional[str]) -> Optional[Dict[str, object]]:
    identifier = email or sub
    if not identifier and not name:
        return None
    return {
        "actor_type": "admin",
        "actor_id": identifier,
        "actor_name": name,
        "email": email,
        "sub": sub,
    }


def _actor_from_session() -> Optional[Dict[str, object]]:
    user = session.get("user")
    if not isinstance(user, dict):
        return None
    return _build_actor(user.get("email"), user.get("name"), user.get("sub"))


def _log_auth_action(
    action: str,
    *,
    status: str,
    message: Optional[str] = None,
    metadata: Optional[Dict[str, object]] = None,
    actor: Optional[Dict[str, object]] = None,
) -> None:
    audit_record_action(
        action,
        channel="http",
        actor=actor or _actor_from_session(),
        ip_address=_request_ip(),
        resource_type="auth",
        resource_id=action,
        status=status,
        message=message,
        metadata=metadata,
    )


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
    """保護後台路由，要求使用者先登入。"""

    @wraps(func)
    def wrapper(*args, **kwargs):
        if not session.get("user"):
            abort(401, description="尚未登入")
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
        _log_auth_action(
            "auth.login",
            status="failure",
            message="Missing GOOGLE_CLIENT_ID",
            metadata={"reason": "missing_client_id"},
        )
        abort(500, description="尚未設定 GOOGLE_CLIENT_ID")

    data = request.get_json(silent=True) or {}
    credential = data.get("credential")
    if not credential:
        _log_auth_action(
            "auth.login",
            status="failure",
            message="Missing credential",
            metadata={"reason": "missing_credential"},
        )
        abort(400, description="缺少 credential")

    try:
        token_info = id_token.verify_oauth2_token(
            credential,
            google_requests.Request(),
            audience=client_id,
        )
    except ValueError as exc:
        _log_auth_action(
            "auth.login",
            status="failure",
            message="Google token verification failed",
            metadata={"reason": "token_verification_failed", "error": str(exc)},
        )
        abort(401, description=f"Google 登入驗證失敗：{exc}")

    actor = _build_actor(token_info.get("email"), token_info.get("name"), token_info.get("sub"))
    if not _is_authorized(token_info.get("email"), allowed_emails, allowed_domains):
        _log_auth_action(
            "auth.login",
            status="failure",
            message="Email not allowed",
            metadata={"reason": "unauthorized_email", "email": token_info.get("email")},
            actor=actor,
        )
        abort(403, description="此帳號不在允許清單中")

    session["user"] = _build_user_payload(token_info)
    _log_auth_action(
        "auth.login",
        status="success",
        metadata={"email": session["user"].get("email")},
    )
    return jsonify({"authenticated": True, "user": session["user"]})


@auth_bp.post("/logout")
def auth_logout():
    previous_user = session.pop("user", None)
    actor = None
    if isinstance(previous_user, dict):
        actor = _build_actor(previous_user.get("email"), previous_user.get("name"), previous_user.get("sub"))
    _log_auth_action(
        "auth.logout",
        status="success",
        actor=actor,
        metadata={"had_session": bool(previous_user)},
    )
    return jsonify({"authenticated": False})
