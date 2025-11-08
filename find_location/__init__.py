"""Route location lookup helpers."""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple
from functools import lru_cache

from linebot import LineBotApi
from linebot.models import (
    CarouselColumn,
    CarouselTemplate,
    LocationAction,
    LocationMessage,
    LocationSendMessage,
    MessageAction,
    MessageEvent,
    QuickReply,
    QuickReplyButton,
    TemplateSendMessage,
    TextSendMessage,
)

from demos.state import get_topic, set_topic


FIND_LOCATION_TOPIC = "Find location"
_DISTANCE_TRIGGERS = {"里程轉座標", "里程轉坐標"}
_COORDINATE_TRIGGERS = {"座標轉里程", "坐標轉里程"}
_CANCEL_KEYWORDS = {"取消", "結束", "退出"}
_NUMBER_PATTERN = re.compile(r"[-+]?\d+(?:\.\d+)?")

_DATA_PATH = Path(__file__).resolve().parents[1] / "data.json"


def _load_line_data() -> Dict[str, List[Dict[str, float]]]:
    if not _DATA_PATH.exists():
        print(f"Error: 找不到資料檔案 {_DATA_PATH}")
        return {}

    try:
        with _DATA_PATH.open("r", encoding="utf-8") as f:
            raw = json.load(f)
    except json.JSONDecodeError as exc:
        print(f"Error: 讀取資料失敗 - {exc}")
        return {}

    lines: Dict[str, List[Dict[str, float]]] = {}
    for name, entries in raw.get("lines", {}).items():
        sorted_entries = sorted(entries, key=lambda item: item["diatance"])
        lines[name] = sorted_entries
    return lines


_LINE_DATA = _load_line_data()
_LINE_NAMES = list(_LINE_DATA.keys())


def _normalize_line_identifier(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


_LINE_NAME_BY_NORMALIZED = {
    _normalize_line_identifier(name): name for name in _LINE_NAMES
}


def _resolve_line_name(text: str) -> Optional[str]:
    normalized = _normalize_line_identifier(text)
    if not normalized:
        return None
    if normalized in _LINE_NAME_BY_NORMALIZED:
        return _LINE_NAME_BY_NORMALIZED[normalized]
    for key, name in _LINE_NAME_BY_NORMALIZED.items():
        if normalized.startswith(key):
            return name
    return None


def _compute_reference_latitude() -> Optional[float]:
    total = 0.0
    count = 0
    for path in _LINE_DATA.values():
        for entry in path:
            total += entry["latitude"]
            count += 1
    if count == 0:
        return None
    return total / count


_REF_LATITUDE = _compute_reference_latitude()


def _to_xy(longitude: float, latitude: float) -> Tuple[float, float]:
    radius = 6_371_000.0
    ref_lat_rad = math.radians(_REF_LATITUDE if _REF_LATITUDE is not None else latitude)
    x = math.radians(longitude) * radius * math.cos(ref_lat_rad)
    y = math.radians(latitude) * radius
    return x, y


def _get_xy(entry: Dict[str, float]) -> Tuple[float, float]:
    if "_x" not in entry or "_y" not in entry:
        entry["_x"], entry["_y"] = _to_xy(entry["longitude"], entry["latitude"])
    return entry["_x"], entry["_y"]


@dataclass
class SessionState:
    mode: str
    stage: str
    line_name: Optional[str] = None
    longitude: Optional[float] = None
    latitude: Optional[float] = None


_SESSIONS: Dict[str, SessionState] = {}


def _source_key(event: MessageEvent) -> str:
    source = event.source
    if getattr(source, "user_id", None):
        return f"user:{source.user_id}"
    if getattr(source, "group_id", None):
        return f"group:{source.group_id}"
    if getattr(source, "room_id", None):
        return f"room:{source.room_id}"
    return "global"


def _chunked(seq: Sequence[MessageAction], size: int) -> List[List[MessageAction]]:
    return [list(seq[i : i + size]) for i in range(0, len(seq), size)]


def _build_line_selection_messages() -> List[TemplateSendMessage]:
    columns = [
        CarouselColumn(
            title="路線選擇",
            text=name[:60],
            actions=[MessageAction(label="使用這條路線", text=name)],
        )
        for name in _LINE_NAMES
    ]

    groups = _chunked(columns, 10) or [[]]
    total_groups = len(groups)
    messages: List[TemplateSendMessage] = []
    for index, group in enumerate(groups, start=1):
        if not group:
            continue
        template = CarouselTemplate(columns=group)
        messages.append(
            TemplateSendMessage(
                alt_text=f"里程轉座標 - 選擇路線 {index}/{total_groups}",
                template=template,
            )
        )
    return messages


def _build_coordinate_prompt(text: str) -> TextSendMessage:
    quick_reply = QuickReply(
        items=[
            QuickReplyButton(action=LocationAction(label="分享位置")),
            QuickReplyButton(action=MessageAction(label="取消", text="取消")),
        ]
    )
    return TextSendMessage(text=text, quick_reply=quick_reply)


def _format_distance_marker(distance: float) -> str:
    km = int(distance // 1000)
    meters = distance - km * 1000
    if abs(meters - round(meters)) < 1e-4:
        meters = float(round(meters))

    if meters.is_integer():
        meter_text = f"{int(meters):03d}"
    else:
        meter_text = f"{meters:.3f}".rstrip("0").rstrip(".")

    return f"K{km}+{meter_text}"


@lru_cache(maxsize=None)
def _get_line_bounds(line_name: str) -> Tuple[str, str, str]:
    path = _LINE_DATA.get(line_name)
    if not path:
        return "", "", ""

    start_entry = path[0]
    end_entry = path[-1]
    start_name = start_entry.get("name") or _format_distance_marker(start_entry["diatance"])
    end_name = end_entry.get("name") or _format_distance_marker(end_entry["diatance"])
    start_distance = start_entry["diatance"]
    end_distance = end_entry["diatance"]
    sample_distance = start_distance
    span = end_distance - start_distance
    if span > 0:
        sample_distance = start_distance + min(max(100.0, span * 0.05), span)

    sample_marker = _format_distance_marker(sample_distance)
    return start_name, end_name, sample_marker


def _interpolate_coordinates(line_name: str, distance: float) -> Optional[Tuple[float, float]]:
    path = _LINE_DATA.get(line_name)
    if not path:
        return None

    if distance < path[0]["diatance"]:
        return None
    if distance > path[-1]["diatance"]:
        return None

    for idx in range(len(path) - 1):
        start = path[idx]
        end = path[idx + 1]
        start_d = start["diatance"]
        end_d = end["diatance"]
        if start_d <= distance <= end_d:
            span = end_d - start_d
            factor = 0 if span == 0 else (distance - start_d) / span
            longitude = start["longitude"] + factor * (end["longitude"] - start["longitude"])
            latitude = start["latitude"] + factor * (end["latitude"] - start["latitude"])
            return (longitude, latitude)

    return None


def _distance_to_segment(
    px: float,
    py: float,
    ax: float,
    ay: float,
    bx: float,
    by: float,
) -> Tuple[float, float]:
    abx = bx - ax
    aby = by - ay
    ab_len_sq = abx * abx + aby * aby
    if ab_len_sq == 0:
        dx = px - ax
        dy = py - ay
        return 0.0, dx * dx + dy * dy

    apx = px - ax
    apy = py - ay
    t = (apx * abx + apy * aby) / ab_len_sq
    t = max(0.0, min(1.0, t))
    closest_x = ax + t * abx
    closest_y = ay + t * aby
    dx = px - closest_x
    dy = py - closest_y
    return t, dx * dx + dy * dy


def _find_nearest_marker(longitude: float, latitude: float) -> Optional[Tuple[str, float, float]]:
    best_line: Optional[str] = None
    best_distance: Optional[float] = None
    best_error_sq = math.inf
    point_x, point_y = _to_xy(longitude, latitude)
    for name, path in _LINE_DATA.items():
        for idx in range(len(path) - 1):
            start = path[idx]
            end = path[idx + 1]
            start_x, start_y = _get_xy(start)
            end_x, end_y = _get_xy(end)
            t, error_sq = _distance_to_segment(
                point_x,
                point_y,
                start_x,
                start_y,
                end_x,
                end_y,
            )
            if error_sq < best_error_sq:
                segment_distance = start["diatance"] + t * (end["diatance"] - start["diatance"])
                best_line = name
                best_distance = segment_distance
                best_error_sq = error_sq

    if best_line is None or best_distance is None:
        return None
    return best_line, best_distance, math.sqrt(best_error_sq)


def _parse_distance(text: str) -> Optional[float]:
    normalized = text.upper().replace("Ｋ", "K").replace("＋", "+").replace("，", ",")
    normalized = normalized.replace(" ", "")
    numbers = [float(match) for match in _NUMBER_PATTERN.findall(normalized)]
    if not numbers:
        return None

    has_k = "K" in normalized or "公里" in text
    if has_k:
        km = numbers[0]
        meters = numbers[1] if len(numbers) > 1 else 0.0
        return km * 1000 + meters

    return numbers[0]


def _parse_coordinate_value(text: str) -> Optional[float]:
    match = _NUMBER_PATTERN.search(text)
    if not match:
        return None
    return float(match.group(0))


def _extract_two_numbers(text: str) -> Tuple[Optional[float], Optional[float]]:
    numbers = [float(value) for value in _NUMBER_PATTERN.findall(text)]
    if not numbers:
        return None, None
    if len(numbers) == 1:
        return numbers[0], None
    return numbers[0], numbers[1]


def _get_session(event: MessageEvent) -> Optional[SessionState]:
    return _SESSIONS.get(_source_key(event))


def _set_session(event: MessageEvent, state: SessionState) -> None:
    _SESSIONS[_source_key(event)] = state
    set_topic(FIND_LOCATION_TOPIC)


def _clear_session(event: MessageEvent) -> None:
    _SESSIONS.pop(_source_key(event), None)
    set_topic(None)


def _start_distance_mode(event: MessageEvent, line_bot_api: LineBotApi) -> None:
    _set_session(
        event,
        SessionState(mode="distance_to_coordinates", stage="awaiting_line"),
    )
    if not _LINE_NAMES:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="查無路線資料，請稍後再試。"),
        )
        _clear_session(event)
        return
    messages = _build_line_selection_messages()
    line_bot_api.reply_message(event.reply_token, messages)


def _start_coordinate_mode(event: MessageEvent, line_bot_api: LineBotApi) -> None:
    _set_session(
        event,
        SessionState(mode="coordinates_to_distance", stage="awaiting_longitude"),
    )
    reply = _build_coordinate_prompt("請提供經度")
    line_bot_api.reply_message(event.reply_token, reply)


def _handle_line_selection(
    event: MessageEvent,
    line_bot_api: LineBotApi,
    session: SessionState,
    incoming_text: str,
) -> bool:
    resolved_name = _resolve_line_name(incoming_text)
    if not resolved_name:
        options = "、".join(_LINE_NAMES[:4])
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=f"找不到這條路線，請直接點選按鈕或輸入例如：{options}"),
        )
        return True

    session.line_name = resolved_name
    session.stage = "awaiting_distance"
    start_marker, end_marker, sample_marker = _get_line_bounds(resolved_name)
    range_text = ""
    if start_marker and end_marker:
        range_text = f" (起 {start_marker} 迄 {end_marker})"
    example_marker = sample_marker or "K0+100"
    prompt = TextSendMessage(
        text=f"請問 {resolved_name}{range_text}要查詢多少里程？（例如：{example_marker}）"
    )
    line_bot_api.reply_message(event.reply_token, prompt)
    return True


def _handle_distance_value(
    event: MessageEvent,
    line_bot_api: LineBotApi,
    session: SessionState,
    incoming_text: str,
) -> bool:
    if not session.line_name:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="請先選擇路線。"),
        )
        session.stage = "awaiting_line"
        return True

    distance = _parse_distance(incoming_text)
    if distance is None:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="無法判讀里程，請再輸入一次，例如：K3+250。"),
        )
        return True

    coords = _interpolate_coordinates(session.line_name, distance)
    if coords is None:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="超出路線範圍，請確認里程是否正確。"),
        )
        return True

    longitude, latitude = coords
    marker = _format_distance_marker(distance)
    line_bot_api.reply_message(
        event.reply_token,
        [
            TextSendMessage(text=f"這個地點經度為 {longitude:.6f}, 緯度為 {latitude:.6f}"),
            LocationSendMessage(
                title=f"{session.line_name} {marker}",
                address="里程轉座標結果",
                latitude=latitude,
                longitude=longitude,
            ),
        ],
    )
    _clear_session(event)
    return True


def _handle_coordinate_text(
    event: MessageEvent,
    line_bot_api: LineBotApi,
    session: SessionState,
    incoming_text: str,
) -> bool:
    if session.stage == "awaiting_longitude":
        lon, lat = _extract_two_numbers(incoming_text)
        if lon is None:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="請提供經度數值，例如：121.7298。"),
            )
            return True
        session.longitude = lon
        if lat is not None:
            session.latitude = lat
            return _respond_with_location(event, line_bot_api, session)
        session.stage = "awaiting_latitude"
        reply = _build_coordinate_prompt("請提供緯度")
        line_bot_api.reply_message(event.reply_token, reply)
        return True

    if session.stage == "awaiting_latitude":
        value = _parse_coordinate_value(incoming_text)
        if value is None:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="請提供緯度數值，例如：25.1089。"),
            )
            return True
        session.latitude = value
        return _respond_with_location(event, line_bot_api, session)

    return False


def _respond_with_location(
    event: MessageEvent,
    line_bot_api: LineBotApi,
    session: SessionState,
) -> bool:
    if session.longitude is None or session.latitude is None:
        return False

    result = _find_nearest_marker(session.longitude, session.latitude)
    if result is None:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="附近找不到對應的路線里程，請再確認座標。"),
        )
        return True

    line_name, distance, offset = result
    marker = _format_distance_marker(distance)
    if offset > 10:
        distance_text = int(round(offset))
        message = f"距離座標最近的路線為「{line_name}{marker}」，距離{distance_text}公尺"
    else:
        message = f"這個地點為 {line_name} {marker}"
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=message),
    )
    _clear_session(event)
    return True


def handle_message_event(event: MessageEvent, line_bot_api: LineBotApi) -> bool:
    incoming_text = (event.message.text or "").strip()
    if not incoming_text:
        return False

    normalized = incoming_text.replace(" ", "")

    if normalized in _CANCEL_KEYWORDS:
        if _get_session(event):
            _clear_session(event)
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="已取消查詢。"),
            )
            return True
        return False

    if normalized in _DISTANCE_TRIGGERS:
        _start_distance_mode(event, line_bot_api)
        return True

    if normalized in _COORDINATE_TRIGGERS:
        _start_coordinate_mode(event, line_bot_api)
        return True

    session = _get_session(event)
    if session is None:
        return False

    if get_topic() != FIND_LOCATION_TOPIC:
        return False

    if session.mode == "distance_to_coordinates":
        if session.stage == "awaiting_line":
            return _handle_line_selection(event, line_bot_api, session, incoming_text)
        if session.stage == "awaiting_distance":
            return _handle_distance_value(event, line_bot_api, session, incoming_text)
        return False

    if session.mode == "coordinates_to_distance":
        return _handle_coordinate_text(event, line_bot_api, session, incoming_text)

    return False


def handle_location_message(event: MessageEvent, line_bot_api: LineBotApi) -> bool:
    session = _get_session(event)
    if session is None or session.mode != "coordinates_to_distance":
        return False

    session.longitude = event.message.longitude
    session.latitude = event.message.latitude
    return _respond_with_location(event, line_bot_api, session)


def list_line_names() -> List[str]:
    """Return available route names."""
    return list(_LINE_NAMES)


def format_distance_marker(distance: float) -> str:
    """Expose distance marker formatter for other modules."""
    return _format_distance_marker(distance)


def resolve_route_coordinate(
    line_text: str,
    marker_text: str,
) -> Optional[Tuple[str, float, float, float]]:
    """Resolve a (line, marker) pair into coordinates."""
    line_name = _resolve_line_name(line_text)
    if not line_name:
        return None

    distance = _parse_distance(marker_text)
    if distance is None:
        return None

    coords = _interpolate_coordinates(line_name, distance)
    if coords is None:
        return None

    longitude, latitude = coords
    return line_name, distance, longitude, latitude


__all__ = [
    "handle_message_event",
    "handle_location_message",
    "FIND_LOCATION_TOPIC",
    "list_line_names",
    "format_distance_marker",
    "resolve_route_coordinate",
]
