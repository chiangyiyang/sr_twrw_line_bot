"""LINE 查詢雨量的對話模組。"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from linebot import LineBotApi
from linebot.models import (
    LocationAction,
    LocationMessage,
    MessageAction,
    MessageEvent,
    QuickReply,
    QuickReplyButton,
    TextSendMessage,
)
from ..demos.state import get_topic, set_topic
from ..rainfall_service import get_public_page_url, repository
from ..rainfall_service.models import StationObservation

CHECK_RAINFALL_TOPIC = "Check rainfall"
_TRIGGERS = {"查雨量", "雨量站", "查詢雨量", "下雨嗎"}
_MODE_LABELS = {
    "雨量查詢：座標": "coordinate",
    "雨量查詢：測站": "station",
    "雨量查詢：行政區": "district",
}
_COORD_PATTERN = re.compile(r"[-+]?\d+(?:\.\d+)?")


@dataclass
class Session:
    mode: str
    stage: str


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


def _build_entry_message() -> TextSendMessage:
    quick_reply = QuickReply(
        items=[
            QuickReplyButton(action=MessageAction(label=label.split("：")[1], text=label))
            for label in _MODE_LABELS
        ]
    )
    return TextSendMessage(
        text="請選擇要查詢雨量的方式，可以依照座標、測站名稱或行政區查詢。",
        quick_reply=quick_reply,
    )


def _coordinate_prompt() -> TextSendMessage:
    quick_reply = QuickReply(
        items=[
            QuickReplyButton(action=LocationAction(label="分享位置")),
            QuickReplyButton(action=MessageAction(label="取消", text="取消雨量查詢")),
        ]
    )
    return TextSendMessage(
        text="請輸入經度與緯度，例如「121.446,24.925」，或直接分享位置。",
        quick_reply=quick_reply,
    )


def _station_prompt() -> TextSendMessage:
    return TextSendMessage(text="請輸入測站名稱或測站代碼，例如：建安國小 或 81AI10。")


def _district_prompt() -> TextSendMessage:
    return TextSendMessage(text="請輸入縣市與行政區，例如：新北市 新店區。只輸入縣市也可以。")


def _set_session(key: str, session: Optional[Session]) -> None:
    if session is None:
        _SESSIONS.pop(key, None)
    else:
        _SESSIONS[key] = session


def _parse_coordinate_text(text: str) -> Tuple[Optional[float], Optional[float]]:
    numbers = _COORD_PATTERN.findall(text.replace("，", ",").replace("；", ","))
    if len(numbers) >= 2:
        try:
            lon = float(numbers[0])
            lat = float(numbers[1])
            return lon, lat
        except ValueError:
            return None, None
    return None, None


def _format_rain(value: Optional[float]) -> str:
    if value is None:
        return "-"
    return f"{value:.1f}"


def _format_observation(item: StationObservation) -> str:
    location_bits: List[str] = []
    if item.city:
        location_bits.append(item.city)
    if item.town:
        if location_bits:
            location_bits[-1] = f"{location_bits[-1]} {item.town}"
        else:
            location_bits.append(item.town)

    location_text = "".join(location_bits)
    coords_text = f"（ {item.longitude:.5f}, {item.latitude:.5f} ）"
    attr_text = item.attribute or "-"
    elev_text = "-" if item.elevation is None else f"{item.elevation:.1f}"

    lines = [
        f"{item.station_name}（{item.station_id}）",
        f"觀測時間：{item.obs_time}",
        f"位置：{location_text}{coords_text}",
        f"海拔：{elev_text} m　屬性：{attr_text}",
        (
            f"10 分：{_format_rain(item.min_10)} mm　 1 小時：{_format_rain(item.hour_1)} mm　"
            f" 3 小時：{_format_rain(item.hour_3)} mm"
        ),
        (
            f"6 小時：{_format_rain(item.hour_6)} mm　 12 小時：{_format_rain(item.hour_12)} mm　"
            f" 24 小時：{_format_rain(item.hour_24)} mm"
        ),
    ]
    return "\n".join(lines)


def _format_response(items: List[StationObservation]) -> str:
    if not items:
        return "查無對應的雨量資料，請換個條件或稍後再試。"
    formatted = "\n\n".join(_format_observation(item) for item in items)
    return formatted


def _reply_with_results(event: MessageEvent, line_bot_api: LineBotApi, items: List[StationObservation]) -> None:
    page_url = get_public_page_url()
    text = _format_response(items)
    link_text = f"查看更多雨量資訊：{page_url}"
    line_bot_api.reply_message(
        event.reply_token,
        [
            TextSendMessage(text=text),
            TextSendMessage(text=link_text),
        ],
    )


def _handle_coordinate_query(event: MessageEvent, line_bot_api: LineBotApi, longitude: float, latitude: float) -> bool:
    items = repository.search_nearest_by_coordinate(longitude, latitude, limit=3)
    _reply_with_results(event, line_bot_api, items)
    _set_session(_source_key(event), None)
    set_topic(None)
    return True


def _handle_station_query(event: MessageEvent, line_bot_api: LineBotApi, keyword: str) -> bool:
    items = repository.search_by_station_name(keyword, limit=5)
    _reply_with_results(event, line_bot_api, items)
    _set_session(_source_key(event), None)
    set_topic(None)
    return True


def _handle_district_query(event: MessageEvent, line_bot_api: LineBotApi, text: str) -> bool:
    sanitized = re.split(r"[\s,，]+", text.strip(), maxsplit=1)
    if not sanitized or not sanitized[0]:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="請輸入縣市或縣市＋行政區。"))
        return True
    city = sanitized[0]
    town = sanitized[1] if len(sanitized) > 1 else None
    items = repository.search_by_district(city, town, limit=20)
    _reply_with_results(event, line_bot_api, items)
    _set_session(_source_key(event), None)
    set_topic(None)
    return True


def handle_message_event(event: MessageEvent, line_bot_api: LineBotApi) -> bool:
    incoming_text = (event.message.text or "").strip()
    source = _source_key(event)

    if incoming_text in _TRIGGERS:
        set_topic(CHECK_RAINFALL_TOPIC)
        _set_session(source, None)
        line_bot_api.reply_message(
            event.reply_token,
            _build_entry_message(),
        )
        return True

    if incoming_text == "取消雨量查詢":
        if _SESSIONS.pop(source, None):
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="已取消雨量查詢。"))
            return True
        return False

    if incoming_text in _MODE_LABELS:
        set_topic(CHECK_RAINFALL_TOPIC)
        mode = _MODE_LABELS[incoming_text]
        session = Session(mode=mode, stage="awaiting_input")
        _set_session(source, session)
        if mode == "coordinate":
            line_bot_api.reply_message(event.reply_token, _coordinate_prompt())
        elif mode == "station":
            line_bot_api.reply_message(event.reply_token, _station_prompt())
        elif mode == "district":
            line_bot_api.reply_message(event.reply_token, _district_prompt())
        return True

    if get_topic() != CHECK_RAINFALL_TOPIC:
        return False

    session = _SESSIONS.get(source)
    if not session:
        return False

    if session.mode == "coordinate":
        lon, lat = _parse_coordinate_text(incoming_text)
        if lon is None or lat is None:
            line_bot_api.reply_message(event.reply_token, _coordinate_prompt())
            return True
        return _handle_coordinate_query(event, line_bot_api, lon, lat)
    if session.mode == "station":
        return _handle_station_query(event, line_bot_api, incoming_text or "")
    if session.mode == "district":
        return _handle_district_query(event, line_bot_api, incoming_text or "")

    return False


def handle_location_message(event: MessageEvent, line_bot_api: LineBotApi) -> bool:
    source = _source_key(event)
    session = _SESSIONS.get(source)
    if not session or session.mode != "coordinate":
        return False
    return _handle_coordinate_query(event, line_bot_api, event.message.longitude, event.message.latitude)


__all__ = ["handle_message_event", "handle_location_message", "CHECK_RAINFALL_TOPIC"]
