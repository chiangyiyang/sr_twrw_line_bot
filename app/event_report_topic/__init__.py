"""LINE 事件回報模組。"""
from __future__ import annotations

import mimetypes
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from uuid import uuid4

from linebot import LineBotApi
from linebot.exceptions import LineBotApiError
from linebot.models import (
    CameraAction,
    CameraRollAction,
    LocationAction,
    LocationMessage,
    MessageAction,
    MessageEvent,
    QuickReply,
    QuickReplyButton,
    TextSendMessage,
)

from .. import state
from . import repository
from .models import ReportEventRecord
from .public import get_public_page_url
from ..location_topic import format_distance_marker, resolve_route_coordinate
from ..paths import EVENT_PICTURES_DIR
from ..audit_log import record_action as audit_record_action
from .photos import serialize_photo_field


REPORT_EVENT_TOPIC = "Report event"
_TRIGGERS = {"回報事件", "事件回報", "災情回報"}
_CANCEL_KEYWORDS = {"取消", "結束", "退出", "取消事件回報", "結束事件回報", "退出事件回報"}
_CONFIRM_YES = {"是", "是的", "確認", "沒問題", "ok", "ok的", "ＯＫ"}
_CONFIRM_NO = {"否", "不是", "重新輸入", "不正確", "否定"}

_EVENT_TYPES = ["土石滑落", "落石", "路樹侵入", "其他"]
_LOCATION_METHOD_OPTIONS = ["軌道里程", "位置座標"]
_ROUTE_LINES = ["平溪線", "深澳線", "宜蘭線", "北迴線"]
_ROUTE_LINES_LEFT_RIGHT = {"平溪線", "深澳線"}
_ROUTE_LINES_EAST_WEST = {"宜蘭線", "北迴線"}
_LEFT_RIGHT_CHOICES = ["左", "右"]
_EAST_WEST_CHOICES = ["東", "西"]
_MILEAGE_PATTERN = re.compile(r"^(?:k|K)?\s*(\d+)(?:\+(\d+))?$")
_COORD_PATTERN = re.compile(r"[-+]?\d+(?:\.\d+)?")
_PHOTO_DONE_KEYWORDS = {"完成", "完成上傳", "上傳完成", "好了", "結束上傳"}

_PICTURE_DIR = EVENT_PICTURES_DIR


def _append_query_params(base_url: str, params: Dict[str, object]) -> str:
    if not params:
        return base_url
    parsed = urlparse(base_url)
    existing = dict(parse_qsl(parsed.query, keep_blank_values=True))
    for key, value in params.items():
        if value is None:
            continue
        existing[key] = str(value)
    new_query = urlencode(existing, doseq=True)
    return urlunparse(parsed._replace(query=new_query))


def _event_public_link(base_url: str, record: ReportEventRecord) -> str:
    params: Dict[str, object] = {}
    if record.id:
        params["event_id"] = record.id
    if isinstance(record.longitude, (int, float)) and isinstance(record.latitude, (int, float)):
        params["lon"] = f"{float(record.longitude):.6f}"
        params["lat"] = f"{float(record.latitude):.6f}"
    if not params:
        return base_url
    return _append_query_params(base_url, params)


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", "", (text or "")).lower()


_TRIGGER_TOKENS = {_normalize_text(item) for item in _TRIGGERS}
_CANCEL_TOKENS = {_normalize_text(item) for item in _CANCEL_KEYWORDS}
_CONFIRM_YES_TOKENS = {_normalize_text(item) for item in _CONFIRM_YES}
_CONFIRM_NO_TOKENS = {_normalize_text(item) for item in _CONFIRM_NO}
_PHOTO_DONE_TOKENS = {_normalize_text(item) for item in _PHOTO_DONE_KEYWORDS}


def _cancel_button() -> QuickReplyButton:
    return QuickReplyButton(action=MessageAction(label="取消", text="取消"))


def _confirm_quick_reply() -> QuickReply:
    return QuickReply(
        items=[
            QuickReplyButton(action=MessageAction(label="是", text="是")),
            QuickReplyButton(action=MessageAction(label="否", text="否")),
            _cancel_button(),
        ]
    )


@dataclass
class Session:
    stage: str
    event_type: Optional[str] = None
    location_mode: Optional[str] = None
    route_line: Optional[str] = None
    track_side: Optional[str] = None
    mileage_text: Optional[str] = None
    mileage_meters: Optional[float] = None
    photo_filenames: List[str] = field(default_factory=list)
    longitude: Optional[float] = None
    latitude: Optional[float] = None
    location_title: Optional[str] = None
    location_address: Optional[str] = None


_SESSIONS: Dict[str, Session] = {}


def _source_key(event: MessageEvent) -> str:
    source = event.source
    if getattr(source, "user_id", None):
        return f"user:{source.user_id}"
    if getattr(source, "group_id", None):
        return f"group:{source.group_id}"
    if getattr(source, "room_id", None):
        return f"room:{source.room_id}"
    return "unknown"


def _set_session(key: str, session: Optional[Session]) -> None:
    if session is None:
        _SESSIONS.pop(key, None)
    else:
        _SESSIONS[key] = session


def _get_session(event: MessageEvent) -> Optional[Session]:
    return _SESSIONS.get(_source_key(event))


def _build_quick_reply(options: Sequence[str]) -> QuickReply:
    items = [
        QuickReplyButton(action=MessageAction(label=item, text=item))
        for item in options
    ]
    items.append(_cancel_button())
    return QuickReply(items=items)


def _start_session(event: MessageEvent, line_bot_api: LineBotApi) -> None:
    key = _source_key(event)
    session = Session(stage="event_type")
    _set_session(key, session)
    state.set_topic(key, REPORT_EVENT_TOPIC)
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(
            text="請選擇要回報的事件類型：",
            quick_reply=_build_quick_reply(_EVENT_TYPES),
        ),
    )


def _prompt_location_method(event: MessageEvent, line_bot_api: LineBotApi) -> None:
    quick_reply = QuickReply(
        items=[
            QuickReplyButton(action=MessageAction(label=option, text=option))
            for option in _LOCATION_METHOD_OPTIONS
        ]
        + [_cancel_button()]
    )
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(
            text="請分享事件地點：",
            quick_reply=quick_reply,
        ),
    )


def _prompt_coordinate_input(event: MessageEvent, line_bot_api: LineBotApi) -> None:
    quick_reply = QuickReply(
        items=[
            QuickReplyButton(action=LocationAction(label="分享位置")),
            _cancel_button(),
        ]
    )
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(
            text="請分享位置或輸入經緯度座標（例如 121.123, 24.123）：",
            quick_reply=quick_reply,
        ),
    )


def _prompt_route_line(event: MessageEvent, line_bot_api: LineBotApi) -> None:
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(
            text="請選擇軌道路線別：",
            quick_reply=_build_quick_reply(_ROUTE_LINES),
        ),
    )


def _prompt_track_side(event: MessageEvent, line_bot_api: LineBotApi, route_line: str) -> None:
    if route_line in _ROUTE_LINES_LEFT_RIGHT:
        text = "請選擇邊別："
        options = _LEFT_RIGHT_CHOICES
    elif route_line in _ROUTE_LINES_EAST_WEST:
        text = "請選擇正線："
        options = _EAST_WEST_CHOICES
    else:
        text = "請選擇邊別／正線："
        options = _EAST_WEST_CHOICES

    quick_reply = QuickReply(
        items=[
            QuickReplyButton(action=MessageAction(label=item, text=item))
            for item in options
        ]
        + [_cancel_button()]
    )
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=text, quick_reply=quick_reply),
    )


def _prompt_mileage(event: MessageEvent, line_bot_api: LineBotApi) -> None:
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text="請輸入里程（例如 K10+100 或 10+100）："),
    )


def _photo_quick_reply() -> QuickReply:
    return QuickReply(
        items=[
            QuickReplyButton(action=CameraAction(label="拍照")),
            QuickReplyButton(action=CameraRollAction(label="相簿")),
            QuickReplyButton(action=MessageAction(label="完成", text="完成")),
            _cancel_button(),
        ]
    )


def _prompt_photo(event: MessageEvent, line_bot_api: LineBotApi) -> None:
    quick_reply = _photo_quick_reply()
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(
            text="請上傳照片（完成後可輸入「完成」繼續）：",
            quick_reply=quick_reply,
        ),
    )


def _reply_with_summary(event: MessageEvent, line_bot_api: LineBotApi, session: Session) -> None:
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(
            text=_format_summary(session),
            quick_reply=_confirm_quick_reply(),
        ),
    )


def _format_summary(session: Session) -> str:
    if session.longitude is not None and session.latitude is not None:
        coord_text = f"{session.longitude:.5f}, {session.latitude:.5f}"
    else:
        coord_text = "-/-"

    photo_count = len(session.photo_filenames)
    photo_text = f"{photo_count} 張" if photo_count else "-"

    lines = [
        f"事件類型：{session.event_type or '-'}",
        f"路線別：{session.route_line or '-'}",
        f"邊別／正線：{session.track_side or '-'}",
        f"里程K：{session.mileage_text or '-'}",
        f"照片：{photo_text}",
        f"位置：{coord_text}",
    ]
    if session.location_title or session.location_address:
        extra = " / ".join(
            bit for bit in [session.location_title, session.location_address] if bit
        )
        if extra:
            lines.append(f"地點描述：{extra}")
    lines.append("請確認資料是否完整正確？請回覆「是」或「否」。")
    return "\n".join(lines)


def _parse_mileage(text: str) -> Tuple[Optional[str], Optional[float]]:
    cleaned = text.replace(" ", "")
    match = _MILEAGE_PATTERN.match(cleaned)
    if not match:
        return None, None
    km = int(match.group(1))
    offset = int(match.group(2) or "0")
    mileage_text = f"{km}+{offset:03d}"
    mileage_meters = km * 1000 + offset
    return mileage_text, float(mileage_meters)


def _parse_coordinate_text(text: str) -> Tuple[Optional[float], Optional[float]]:
    normalized = (
        text.replace("，", ",")
        .replace("、", ",")
        .replace("；", ",")
        .replace(" ", "")
    )
    numbers = _COORD_PATTERN.findall(normalized)
    if len(numbers) < 2:
        return None, None
    try:
        lon = float(numbers[0])
        lat = float(numbers[1])
    except ValueError:
        return None, None
    return lon, lat


def _handle_event_type(event: MessageEvent, session: Session, incoming_text: str, line_bot_api: LineBotApi) -> bool:
    if incoming_text not in _EVENT_TYPES:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="請從選項中選擇事件類型。"),
        )
        return True
    session.event_type = incoming_text
    session.stage = "location_method"
    _prompt_location_method(event, line_bot_api)
    return True


def _handle_location_method(event: MessageEvent, session: Session, incoming_text: str, line_bot_api: LineBotApi) -> bool:
    if incoming_text not in _LOCATION_METHOD_OPTIONS:
        _prompt_location_method(event, line_bot_api)
        return True

    if incoming_text == "軌道里程":
        session.location_mode = "route"
        session.stage = "route_line"
        _prompt_route_line(event, line_bot_api)
        return True

    session.location_mode = "coordinates"
    session.stage = "coordinate"
    _prompt_coordinate_input(event, line_bot_api)
    return True


def _handle_route_line(event: MessageEvent, session: Session, incoming_text: str, line_bot_api: LineBotApi) -> bool:
    if incoming_text not in _ROUTE_LINES:
        _prompt_route_line(event, line_bot_api)
        return True
    session.route_line = incoming_text
    session.stage = "track_side"
    _prompt_track_side(event, line_bot_api, session.route_line)
    return True


def _handle_track_side(event: MessageEvent, session: Session, incoming_text: str, line_bot_api: LineBotApi) -> bool:
    if not session.route_line:
        session.stage = "route_line"
        _prompt_route_line(event, line_bot_api)
        return True

    route_line = session.route_line
    choices = _LEFT_RIGHT_CHOICES if route_line in _ROUTE_LINES_LEFT_RIGHT else _EAST_WEST_CHOICES
    normalized = incoming_text.strip()
    selected: Optional[str] = None
    for option in choices:
        if normalized == option:
            selected = option
            break
        if normalized in {f"{option}線", f"{option}側", f"{option}正線"}:
            selected = option
            break

    if selected is None:
        _prompt_track_side(event, line_bot_api, route_line)
        return True

    if route_line in _ROUTE_LINES_LEFT_RIGHT:
        session.track_side = f"{selected}側"
    else:
        session.track_side = f"{selected}正線"

    session.stage = "mileage"
    _prompt_mileage(event, line_bot_api)
    return True


def _handle_mileage(event: MessageEvent, session: Session, incoming_text: str, line_bot_api: LineBotApi) -> bool:
    if session.location_mode != "route":
        session.location_mode = "route"
    if not session.route_line:
        session.stage = "route_line"
        _prompt_route_line(event, line_bot_api)
        return True

    mileage_text, mileage_meters = _parse_mileage(incoming_text)
    if mileage_text is None:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="里程格式不正確，範例：10+100 或 K10+100。"),
        )
        return True
    session.mileage_text = mileage_text
    session.mileage_meters = mileage_meters
    marker_text = (
        format_distance_marker(mileage_meters) if mileage_meters is not None else f"K{mileage_text}"
    )
    coords = resolve_route_coordinate(session.route_line, marker_text)
    if not coords:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="查無該里程座標，請確認輸入範圍後再試一次。"),
        )
        return True

    line_name, resolved_distance, longitude, latitude = coords
    session.route_line = line_name
    session.mileage_meters = resolved_distance
    session.longitude = longitude
    session.latitude = latitude
    session.location_title = None
    session.location_address = None
    session.stage = "photo"
    _prompt_photo(event, line_bot_api)
    return True


def _handle_coordinate_text(event: MessageEvent, session: Session, incoming_text: str, line_bot_api: LineBotApi) -> bool:
    lon, lat = _parse_coordinate_text(incoming_text)
    if lon is None or lat is None:
        _prompt_coordinate_input(event, line_bot_api)
        return True
    session.longitude = lon
    session.latitude = lat
    session.location_title = None
    session.location_address = None
    session.location_mode = "coordinates"
    session.stage = "photo"
    _prompt_photo(event, line_bot_api)
    return True


def _handle_photo_stage_text(event: MessageEvent, session: Session, incoming_text: str, line_bot_api: LineBotApi) -> bool:
    normalized = _normalize_text(incoming_text)
    if normalized in _PHOTO_DONE_TOKENS:
        if not session.photo_filenames:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(
                    text="請先上傳至少一張照片，再輸入「完成」。",
                    quick_reply=_photo_quick_reply(),
                ),
            )
            return True
        session.stage = "confirm"
        _reply_with_summary(event, line_bot_api, session)
        return True

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(
            text="請先上傳照片，完成後輸入「完成」或直接再傳照片。",
            quick_reply=_photo_quick_reply(),
        ),
    )
    return True


def _handle_confirmation(event: MessageEvent, session: Session, incoming_text: str, line_bot_api: LineBotApi) -> bool:
    normalized = _normalize_text(incoming_text)
    if normalized in _CONFIRM_YES_TOKENS:
        record = ReportEventRecord(
            id=None,
            event_type=session.event_type or "",
            route_line=session.route_line or "",
            track_side=session.track_side or "",
            mileage_text=session.mileage_text or "",
            mileage_meters=session.mileage_meters,
            photo_filename=serialize_photo_field(session.photo_filenames),
            longitude=session.longitude,
            latitude=session.latitude,
            location_title=session.location_title,
            location_address=session.location_address,
            source_type=_resolve_source_type(event),
            source_id=_resolve_source_id(event),
        )
        repository.save_report(record)
        audit_record_action(
            "events.reported_via_line",
            channel="line",
            actor_type=_resolve_source_type(event),
            actor_id=_resolve_source_id(event),
            resource_type="reported_event",
            resource_id=str(record.id) if record.id else None,
            metadata={
                "event_type": record.event_type,
                "route_line": record.route_line,
                "track_side": record.track_side,
                "mileage_text": record.mileage_text,
                "has_photo": bool(record.photo_filename),
            },
        )
        key = _source_key(event)
        _set_session(key, None)
        state.set_topic(key, None)
        page_url = _event_public_link(get_public_page_url(), record)
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(
                text=f"已完成事件回報，感謝提供資訊！\n可於 {page_url} 檢視事件分佈圖。",
            ),
        )
        return True

    if normalized in _CONFIRM_NO_TOKENS:
        key = _source_key(event)
        _set_session(key, None)
        state.set_topic(key, None)
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="已取消此次回報，如需重新填寫可再次輸入「回報事件」。"),
        )
        return True

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text="請輸入「是」或「否」，以確認資料是否正確。"),
    )
    return True


def _resolve_source_type(event: MessageEvent) -> Optional[str]:
    source = event.source
    if getattr(source, "type", None):
        return source.type
    if getattr(source, "user_id", None):
        return "user"
    if getattr(source, "group_id", None):
        return "group"
    if getattr(source, "room_id", None):
        return "room"
    return None


def _resolve_source_id(event: MessageEvent) -> Optional[str]:
    source = event.source
    if getattr(source, "user_id", None):
        return source.user_id
    if getattr(source, "group_id", None):
        return source.group_id
    if getattr(source, "room_id", None):
        return source.room_id
    return None


def _handle_cancel(event: MessageEvent, line_bot_api: LineBotApi) -> bool:
    if _get_session(event) is None:
        return False
    key = _source_key(event)
    _set_session(key, None)
    state.set_topic(key, None)
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text="已取消事件回報。"),
    )
    return True


def handle_message_event(event: MessageEvent, line_bot_api: LineBotApi) -> bool:
    incoming_text = (event.message.text or "").strip()
    if not incoming_text:
        return False

    normalized = _normalize_text(incoming_text)

    if normalized in _CANCEL_TOKENS:
        return _handle_cancel(event, line_bot_api)

    if normalized in _TRIGGER_TOKENS:
        _start_session(event, line_bot_api)
        return True

    session = _get_session(event)
    if session is None or state.get_topic(_source_key(event)) != REPORT_EVENT_TOPIC:
        return False

    if session.stage == "event_type":
        return _handle_event_type(event, session, incoming_text, line_bot_api)
    if session.stage == "location_method":
        return _handle_location_method(event, session, incoming_text, line_bot_api)
    if session.stage == "route_line":
        return _handle_route_line(event, session, incoming_text, line_bot_api)
    if session.stage == "track_side":
        return _handle_track_side(event, session, incoming_text, line_bot_api)
    if session.stage == "mileage":
        return _handle_mileage(event, session, incoming_text, line_bot_api)
    if session.stage == "coordinate":
        return _handle_coordinate_text(event, session, incoming_text, line_bot_api)
    if session.stage == "photo":
        return _handle_photo_stage_text(event, session, incoming_text, line_bot_api)
    if session.stage == "confirm":
        return _handle_confirmation(event, session, incoming_text, line_bot_api)
    return False


def _ensure_picture_dir() -> None:
    _PICTURE_DIR.mkdir(parents=True, exist_ok=True)


def _guess_extension(content_type: Optional[str]) -> str:
    if not content_type:
        return ".bin"
    ext = mimetypes.guess_extension(content_type)
    if ext:
        return ext
    if content_type == "image/jpeg":
        return ".jpg"
    if content_type == "image/png":
        return ".png"
    return ".bin"


def _save_image_content(event: MessageEvent, line_bot_api: LineBotApi) -> Optional[str]:
    try:
        content = line_bot_api.get_message_content(event.message.id)
    except LineBotApiError as exc:
        print(f"下載照片失敗：{exc}")
        return None

    _ensure_picture_dir()
    ext = _guess_extension(getattr(content, "content_type", None))
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    filename = f"{timestamp}_{uuid4().hex}{ext}"
    path = _PICTURE_DIR / filename
    try:
        with path.open("wb") as fp:
            for chunk in content.iter_content():
                if chunk:
                    fp.write(chunk)
    except OSError as exc:
        print(f"寫入照片檔案失敗：{exc}")
        return None
    return filename


def handle_image_message(event: MessageEvent, line_bot_api: LineBotApi) -> bool:
    session = _get_session(event)
    if session is None or session.stage != "photo":
        return False

    filename = _save_image_content(event, line_bot_api)
    if filename is None:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="照片儲存失敗，請再試一次或改用其他照片。"),
        )
        return True

    session.photo_filenames.append(filename)
    count = len(session.photo_filenames)
    quick_reply = _photo_quick_reply()
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(
            text=f"已收到第 {count} 張照片。若需要繼續請再上傳，完成請輸入「完成」。",
            quick_reply=quick_reply,
        ),
    )
    return True


def handle_location_message(event: MessageEvent, line_bot_api: LineBotApi) -> bool:
    session = _get_session(event)
    if session is None or session.stage != "coordinate":
        return False

    session.longitude = event.message.longitude
    session.latitude = event.message.latitude
    session.location_title = event.message.title
    session.location_address = event.message.address
    session.location_mode = "coordinates"
    session.stage = "photo"
    _prompt_photo(event, line_bot_api)
    return True


__all__ = [
    "handle_message_event",
    "handle_image_message",
    "handle_location_message",
    "REPORT_EVENT_TOPIC",
    "get_public_page_url",
]
