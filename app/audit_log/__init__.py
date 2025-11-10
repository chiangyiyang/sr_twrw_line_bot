"""Audit logging helpers and Flask integration."""
from __future__ import annotations

import json
import sys
from typing import Any, Dict, Iterable, Optional

from flask import Flask, Response, current_app, g, request, session
from werkzeug.exceptions import HTTPException

from . import repository

_DEFAULT_HTTP_PREFIXES: tuple[str, ...] = ("/api/", "/auth/", "/callback")


def _is_enabled(app: Optional[Flask] = None) -> bool:
    if app is None:
        try:
            app = current_app._get_current_object()
        except RuntimeError:
            app = None
    if app is None:
        return True
    return app.config.get("AUDIT_LOG_ENABLED", True)


def _resolve_ip_address() -> Optional[str]:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip() or None
    return request.remote_addr


def _resolve_session_actor() -> Optional[Dict[str, str]]:
    user = session.get("user")
    if not isinstance(user, dict):
        return None
    actor_id = user.get("email") or user.get("sub")
    return {
        "actor_type": "admin",
        "actor_id": actor_id,
        "actor_name": user.get("name"),
        "email": user.get("email"),
    }


def _normalize_actor(
    actor: Optional[Dict[str, Any]],
    actor_type: Optional[str],
    actor_id: Optional[str],
    actor_name: Optional[str],
) -> tuple[Optional[str], Optional[str], Optional[str]]:
    if actor:
        actor_type = actor_type or actor.get("actor_type") or actor.get("type")
        actor_id = actor_id or actor.get("actor_id") or actor.get("id") or actor.get("email")
        actor_name = actor_name or actor.get("actor_name") or actor.get("name")
    return actor_type, actor_id, actor_name


def record_action(
    action_type: str,
    *,
    channel: str = "system",
    actor: Optional[Dict[str, Any]] = None,
    actor_type: Optional[str] = None,
    actor_id: Optional[str] = None,
    actor_name: Optional[str] = None,
    ip_address: Optional[str] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    status: str = "success",
    message: Optional[str] = None,
    metadata: Optional[Any] = None,
) -> Optional[int]:
    """Persist an audit log entry. Swallows DB errors to avoid user impact."""
    if not action_type:
        raise ValueError("action_type is required")
    if not _is_enabled():
        return None
    actor_type, actor_id, actor_name = _normalize_actor(actor, actor_type, actor_id, actor_name)
    details_text: Optional[str] = None
    if metadata is not None:
        try:
            details_text = json.dumps(metadata, ensure_ascii=False)
        except (TypeError, ValueError):
            details_text = json.dumps({"value": str(metadata)}, ensure_ascii=False)
    payload = {
        "action_type": action_type,
        "channel": channel,
        "actor_type": actor_type,
        "actor_id": actor_id,
        "actor_name": actor_name,
        "ip_address": ip_address,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "status": (status or "success").lower(),
        "message": message,
        "details": details_text,
    }
    try:
        return repository.insert_log(payload)
    except Exception as exc:  # pragma: no cover - logging fallback
        print(f"[audit-log] Failed to record action '{action_type}': {exc}", file=sys.stderr)
        return None


def _should_log_request(app: Flask, path: str) -> bool:
    prefixes: Iterable[str] = app.config.get("AUDIT_LOG_HTTP_PREFIXES", _DEFAULT_HTTP_PREFIXES)
    return any(path.startswith(prefix) for prefix in prefixes)


def _finalize_http_audit(app: Flask, response: Optional[Response] = None, error: Optional[BaseException] = None) -> None:
    info = getattr(g, "_audit_request_info", None)
    if not info or getattr(g, "_audit_http_logged", False):
        return
    if not _is_enabled(app):
        return
    info["endpoint"] = request.endpoint or info.get("endpoint")
    info["full_path"] = request.full_path or info.get("full_path")
    status_code: int = 500
    message: Optional[str] = None
    if error is not None:
        if isinstance(error, HTTPException) and error.code:
            status_code = error.code
            message = error.description or error.name
        else:
            status_code = 500
            message = str(error)
    elif response is not None:
        status_code = response.status_code
        message = response.status

    status = "success" if status_code < 400 and error is None else "failure"
    metadata = {
        "method": info.get("method"),
        "path": info.get("path"),
        "query_string": info.get("query_string"),
        "status_code": status_code,
        "user_agent": info.get("user_agent"),
        "endpoint": info.get("endpoint"),
    }
    resource_identifier = info.get("full_path") or info.get("path")
    record_action(
        "http.request",
        channel=info.get("channel") or "http",
        actor=_resolve_session_actor(),
        ip_address=info.get("ip_address"),
        resource_type="http",
        resource_id=resource_identifier,
        status=status,
        message=message,
        metadata=metadata,
    )
    g._audit_http_logged = True


def init_app(app: Flask) -> None:
    """Attach audit logging blueprints and request hooks."""
    app.config.setdefault("AUDIT_LOG_ENABLED", True)
    app.config.setdefault("AUDIT_LOG_HTTP_PREFIXES", _DEFAULT_HTTP_PREFIXES)
    app.config.setdefault("AUDIT_LOG_HTTP_CHANNEL", "http")

    if app.extensions.get("audit_log_initialized"):
        return
    app.extensions["audit_log_initialized"] = True

    @app.before_request
    def _capture_request_for_audit() -> None:  # pragma: no cover - exercised via integration tests
        if not _is_enabled(app):
            return
        path = request.path or ""
        if not _should_log_request(app, path):
            return
        g._audit_request_info = {
            "method": request.method,
            "path": path,
            "full_path": request.full_path,
            "query_string": request.query_string.decode("utf-8", errors="ignore"),
            "ip_address": _resolve_ip_address(),
            "user_agent": request.headers.get("User-Agent"),
            "endpoint": request.endpoint,
            "channel": app.config.get("AUDIT_LOG_HTTP_CHANNEL", "http"),
        }
        g._audit_http_logged = False

    @app.after_request
    def _audit_after_request(response: Response):
        _finalize_http_audit(app, response=response)
        return response

    @app.teardown_request
    def _audit_teardown(error: Optional[BaseException]):  # pragma: no cover - Flask internal flow
        if error is not None:
            _finalize_http_audit(app, error=error)

    from .api import api_bp

    app.register_blueprint(api_bp)


__all__ = ["init_app", "record_action"]
