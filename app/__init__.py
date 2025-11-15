import os
import sys
from typing import Any, Dict, Optional, Set

from flask import Flask, abort, jsonify, render_template, request, send_from_directory
from dotenv import load_dotenv

from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    ImageMessage,
    LocationMessage,
    MessageAction,
    MessageEvent,
    PostbackEvent,
    QuickReply,
    QuickReplyButton,
    TextMessage,
    TextSendMessage,
)

from . import cctv_topic
from . import rainfall_topic
from . import location_topic
from . import rainfall_service
from . import event_report_topic
from .event_report_topic.api import api_bp as report_event_api_bp
from .demos import message_types, quick_replies
from . import state
from .paths import STATIC_DIR, DATA_DIR, EVENT_PICTURES_DIR
from .auth import auth_bp, login_required
from .audit_log import init_app as audit_init_app, record_action as audit_record_action
from .static_data import static_data_bp


load_dotenv()

app = Flask(__name__)
audit_init_app(app)


def _as_env_set(value: str | None) -> Set[str]:
    if not value:
        return set()
    return {item.strip().lower() for item in value.split(",") if item.strip()}


app.secret_key = os.getenv("FLASK_SECRET_KEY") or os.getenv("SECRET_KEY") or "dev-secret-key"
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
if os.getenv("SESSION_COOKIE_SECURE", "0") == "1":
    app.config["SESSION_COOKIE_SECURE"] = True
app.config["GOOGLE_CLIENT_ID"] = os.getenv("GOOGLE_CLIENT_ID", "")
app.config["GOOGLE_ALLOWED_EMAILS"] = _as_env_set(os.getenv("GOOGLE_ALLOWED_EMAILS"))
app.config["GOOGLE_ALLOWED_DOMAINS"] = _as_env_set(os.getenv("GOOGLE_ALLOWED_DOMAINS"))

rainfall_service.init_app(app)
app.register_blueprint(report_event_api_bp)
app.register_blueprint(auth_bp)
app.register_blueprint(static_data_bp)


CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")

if not CHANNEL_SECRET or not CHANNEL_ACCESS_TOKEN:
    print(
        "ERROR: Missing LINE credentials. Set LINE_CHANNEL_SECRET and LINE_CHANNEL_ACCESS_TOKEN.",
        file=sys.stderr,
    )

line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN) if CHANNEL_ACCESS_TOKEN else None
handler = WebhookHandler(CHANNEL_SECRET) if CHANNEL_SECRET else None


def _send_html(filename: str):
    response = send_from_directory(str(STATIC_DIR), filename)
    response.headers.setdefault("Content-Type", "text/html; charset=utf-8")
    return response

STATIC_PAGE_ROUTES = [
    ("/rainfall.html", "rainfall.html", False),
    ("/cctv.html", "cctv.html", False),
    ("/events.html", "events.html", False),
    ("/events_heatmap.html", "events_heatmap.html", False),
    ("/login.html", "login.html", False),
    ("/events_admin.html", "events_admin.html", True),
    ("/audit_logs.html", "audit_logs.html", True),
]


def _make_static_page_handler(filename: str):
    def handler():
        return _send_html(filename)

    handler.__name__ = f"static_page_{filename.replace('.', '_')}"
    return handler


def _register_static_page_routes():
    for route, filename, requires_auth in STATIC_PAGE_ROUTES:
        view_func = _make_static_page_handler(filename)
        if requires_auth:
            view_func = login_required(view_func)
        endpoint = f"static_page_{filename.replace('.', '_')}"
        app.add_url_rule(route, endpoint, view_func)


_register_static_page_routes()


@app.get("/")
def health():
    return {"status": "ok"}


@app.post("/callback")
def callback():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)

    if handler is None:
        abort(500, description="LINE handler not configured")

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400, description="Invalid signature")

    return "OK"


@app.errorhandler(401)
def handle_unauthorized(error):
    description = (getattr(error, "description", None) or "Unauthorized").strip()
    if request.path.startswith("/api/"):
        return jsonify({"error": description, "status": 401}), 401
    if request.path.endswith("events_admin.html"):
        return render_template("errors/401.html", description=description), 401
    return description, 401


def _source_key(event: MessageEvent) -> str:
    source = event.source
    if getattr(source, "user_id", None):
        return f"user:{source.user_id}"
    if getattr(source, "group_id", None):
        return f"group:{source.group_id}"
    if getattr(source, "room_id", None):
        return f"room:{source.room_id}"
    return "unknown"


def _line_actor_info(event) -> tuple[str, Optional[str]]:
    source = event.source
    if getattr(source, "user_id", None):
        return "user", source.user_id
    if getattr(source, "group_id", None):
        return "group", source.group_id
    if getattr(source, "room_id", None):
        return "room", source.room_id
    return "unknown", None


def _line_event_metadata(event) -> Dict[str, Any]:
    metadata: Dict[str, Any] = {"event_type": getattr(event, "type", None)}
    message = getattr(event, "message", None)
    if message is not None:
        metadata["message_type"] = getattr(message, "type", None)
        message_id = getattr(message, "id", None)
        if message_id:
            metadata["message_id"] = message_id
        text_value = getattr(message, "text", None)
        if text_value:
            metadata["text"] = text_value
        if hasattr(message, "latitude") and hasattr(message, "longitude"):
            metadata["latitude"] = getattr(message, "latitude", None)
            metadata["longitude"] = getattr(message, "longitude", None)
        title_value = getattr(message, "title", None)
        if title_value:
            metadata["title"] = title_value
        address_value = getattr(message, "address", None)
        if address_value:
            metadata["address"] = address_value
    postback = getattr(event, "postback", None)
    if postback is not None:
        metadata["postback_data"] = getattr(postback, "data", None)
        metadata["postback_params"] = getattr(postback, "params", None)
    metadata["reply_token"] = getattr(event, "reply_token", None)
    return metadata


def _record_line_event(
    action_type: str,
    event,
    *,
    status: str = "success",
    message: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    actor_type, actor_id = _line_actor_info(event)
    audit_metadata = _line_event_metadata(event)
    if metadata:
        audit_metadata.update(metadata)
    resource_id = audit_metadata.get("message_id") or audit_metadata.get("reply_token")
    audit_record_action(
        action_type,
        channel="line",
        actor_type=actor_type,
        actor_id=actor_id,
        resource_type="line_event",
        resource_id=resource_id,
        status=status,
        message=message,
        metadata=audit_metadata,
    )


TEXT_MESSAGE_HANDLERS = [
    ("rainfall_topic", rainfall_topic.handle_message_event),
    ("cctv_topic", cctv_topic.handle_message_event),
    ("location_topic", location_topic.handle_message_event),
    ("event_report_topic", event_report_topic.handle_message_event),
    ("quick_replies", quick_replies.handle_message_event),
    ("message_types", message_types.handle_message_event),
]


def _dispatch_text_handlers(event: MessageEvent) -> Optional[str]:
    for handler_name, handler in TEXT_MESSAGE_HANDLERS:
        if handler(event, line_bot_api):
            return handler_name
    return None


@handler.add(MessageEvent, message=TextMessage)
def handle_text_message(event: MessageEvent):
    print(f"Received message: {event.message.text}")
    if line_bot_api is None:
        _record_line_event(
            "line.text_message",
            event,
            status="failure",
            message="LINE handler not configured",
        )
        return

    handled_by = _dispatch_text_handlers(event)
    if handled_by:
        _record_line_event(
            "line.text_message",
            event,
            metadata={"handled_by": handled_by},
        )
        return

    source_key = _source_key(event)
    current_topic = state.get_topic(source_key)
    state.set_topic(source_key, None)
    if current_topic is None:
        helper_quick_reply = QuickReply(
            items=[
                QuickReplyButton(action=MessageAction(label="回報事件", text="回報事件")),
                QuickReplyButton(action=MessageAction(label="查雨量", text="查雨量")),
                # QuickReplyButton(action=MessageAction(label="里程轉坐標", text="里程轉坐標")),
                # QuickReplyButton(action=MessageAction(label="坐標轉里程", text="坐標轉里程")),
                QuickReplyButton(action=MessageAction(label="CCTV", text="CCTV")),
                QuickReplyButton(action=MessageAction(label="取消", text="取消")),
            ]
        )
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text='你好，我是「小鐵」，需要協助嗎？', quick_reply=helper_quick_reply),
        )
    else:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=(event.message.text or "")),
        )
    _record_line_event(
        "line.text_message",
        event,
        metadata={"handled_by": "fallback", "previous_topic": current_topic},
    )


@handler.add(PostbackEvent)
def handle_postback_event(event: PostbackEvent):
    if line_bot_api is None:
        _record_line_event(
            "line.postback",
            event,
            status="failure",
            message="LINE handler not configured",
        )
        return

    if quick_replies.handle_postback_event(event, line_bot_api):
        _record_line_event(
            "line.postback",
            event,
            metadata={"handled_by": "quick_replies"},
        )
        return

    _record_line_event(
        "line.postback",
        event,
        metadata={"handled_by": "unhandled"},
    )


@handler.add(MessageEvent, message=LocationMessage)
def handle_location_message(event: MessageEvent):
    if line_bot_api is None:
        _record_line_event(
            "line.location_message",
            event,
            status="failure",
            message="LINE handler not configured",
        )
        return

    handled_by: Optional[str] = None
    if event_report_topic.handle_location_message(event, line_bot_api):
        handled_by = "event_report_topic"
    elif rainfall_topic.handle_location_message(event, line_bot_api):
        handled_by = "rainfall_topic"
    elif cctv_topic.handle_location_message(event, line_bot_api):
        handled_by = "cctv_topic"
    elif location_topic.handle_location_message(event, line_bot_api):
        handled_by = "location_topic"

    if handled_by:
        _record_line_event(
            "line.location_message",
            event,
            metadata={"handled_by": handled_by},
        )
    else:
        _record_line_event(
            "line.location_message",
            event,
            metadata={"handled_by": "unhandled"},
        )


@handler.add(MessageEvent, message=ImageMessage)
def handle_image_message(event: MessageEvent):
    if line_bot_api is None:
        _record_line_event(
            "line.image_message",
            event,
            status="failure",
            message="LINE handler not configured",
        )
        return

    if event_report_topic.handle_image_message(event, line_bot_api):
        _record_line_event(
            "line.image_message",
            event,
            metadata={"handled_by": "event_report_topic"},
        )
        return

    _record_line_event(
        "line.image_message",
        event,
        metadata={"handled_by": "unhandled"},
    )


def main():
    port = int(os.getenv("PORT", "8000"))
    host = os.getenv("HOST", "0.0.0.0")
    debug = os.getenv("FLASK_DEBUG", "0") == "1"
    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    main()
