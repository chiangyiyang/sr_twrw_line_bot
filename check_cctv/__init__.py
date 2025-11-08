"""LINE CCTV 查詢模組。"""
from __future__ import annotations

import json
import math
import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

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

from demos.state import get_topic, set_topic


CHECK_CCTV_TOPIC = "Check CCTV"
_TRIGGERS = {"CCTV", "查CCTV", "查監視器", "CCTV查詢", "監視器查詢"}
_MODE_LABELS = {
    "CCTV查詢：座標": "coordinate",
    "CCTV查詢：名稱": "name",
    "CCTV查詢：行政區": "district",
}
_CANCEL_KEYWORDS = {"取消","取消CCTV查詢", "取消監視器查詢", "結束CCTV查詢", "退出CCTV查詢"}
_COORD_PATTERN = re.compile(r"[-+]?\d+(?:\.\d+)?")
_CLEAN_PATTERN = re.compile(r"[^\w\u4e00-\u9fff]+")
_AREA_PATTERN = re.compile(r"[\u4e00-\u9fff]{1,6}[市縣區鄉鎮里村]")

_DATA_PATH = Path(__file__).resolve().parents[1] / "cctv.json"


@dataclass
class Session:
    mode: str
    stage: str


@dataclass
class CCTVEntry:
    identifier: str
    name: str
    longitude: float
    latitude: float
    url: str
    normalized_name: str
    normalized_id: str
    area_tokens: Sequence[str]

    @property
    def display_name(self) -> str:
        return self.name or self.identifier or "未命名 CCTV"


_SESSIONS: Dict[str, Session] = {}


def _normalize_for_match(text: str) -> str:
    processed = unicodedata.normalize("NFKC", text or "")
    processed = processed.replace("台", "臺").lower()
    return _CLEAN_PATTERN.sub("", processed)


def _tokenize_keywords(text: str) -> List[str]:
    processed = unicodedata.normalize("NFKC", text or "")
    processed = processed.replace("台", "臺").lower()
    chunks = re.split(r"[\s,，、/／]+", processed)
    tokens: List[str] = []
    for chunk in chunks:
        cleaned = _CLEAN_PATTERN.sub("", chunk)
        if cleaned:
            tokens.append(cleaned)
    return tokens


def _extract_area_tokens(text: str) -> List[str]:
    tokens = set()
    for match in _AREA_PATTERN.finditer(text or ""):
        normalized = _normalize_for_match(match.group(0))
        if normalized:
            tokens.add(normalized)
    return sorted(tokens)


def _load_cctv_entries() -> List[CCTVEntry]:
    if not _DATA_PATH.exists():
        print(f"Error: 找不到 CCTV 資料檔 {_DATA_PATH}")
        return []

    try:
        with _DATA_PATH.open("r", encoding="utf-8") as fp:
            raw = json.load(fp)
    except json.JSONDecodeError as exc:
        print(f"Error: 解析 CCTV JSON 失敗 - {exc}")
        return []

    entries: List[CCTVEntry] = []
    for feature in raw.get("features", []):
        geometry = feature.get("geometry") or {}
        coords = geometry.get("coordinates") or []
        if len(coords) < 2:
            continue
        try:
            lon = float(coords[0])
            lat = float(coords[1])
        except (TypeError, ValueError):
            continue

        props = feature.get("properties") or {}
        identifier = str(
            props.get("id") or props.get("ID") or props.get("CCTVID") or props.get("station_id") or ""
        )
        name = str(
            props.get("name")
            or props.get("Location")
            or (props.get("raw_fields") or {}).get("Location")
            or identifier
        )
        url = str(
            props.get("stream_url")
            or props.get("url")
            or (props.get("raw_fields") or {}).get("url")
            or ""
        )
        if not url:
            continue

        normalized_name = _normalize_for_match(name)
        normalized_id = _normalize_for_match(identifier)
        area_tokens = _extract_area_tokens(name)
        entries.append(
            CCTVEntry(
                identifier=identifier,
                name=name if name != identifier else "",
                longitude=lon,
                latitude=lat,
                url=url,
                normalized_name=normalized_name,
                normalized_id=normalized_id,
                area_tokens=area_tokens,
            )
        )
    return entries


_CCTV_ENTRIES = _load_cctv_entries()


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
    return TextSendMessage(text="請選擇要查詢 CCTV 的方式。", quick_reply=quick_reply)


def _coordinate_prompt() -> TextSendMessage:
    quick_reply = QuickReply(
        items=[
            QuickReplyButton(action=LocationAction(label="分享位置")),
            QuickReplyButton(action=MessageAction(label="取消", text="取消CCTV查詢")),
        ]
    )
    return TextSendMessage(text="請輸入經緯度（例如 121.446,24.925），或直接分享位置。", quick_reply=quick_reply)


def _name_prompt() -> TextSendMessage:
    return TextSendMessage(text="請輸入 CCTV 名稱或關鍵字，例：台76線 27K+390。")


def _district_prompt() -> TextSendMessage:
    return TextSendMessage(text="請輸入縣市或行政區關鍵字，例：新北市 新店區 或 新店。")


def _format_distance(meters: float) -> str:
    if meters >= 1000:
        return f"{meters/1000:.1f} 公里"
    return f"{int(round(meters))} 公尺"


def _format_entries(entries: Sequence[CCTVEntry], distances: Optional[Sequence[float]] = None) -> str:
    if not entries:
        return "目前沒有符合條件的 CCTV，請嘗試其他關鍵字。"

    lines: List[str] = []
    for idx, entry in enumerate(entries, 1):
        title = entry.display_name
        distance_text = ""
        if distances and idx - 1 < len(distances):
            distance_text = f"（距離 {_format_distance(distances[idx - 1])}）"
        lines.append(f"{idx}. {title}{distance_text}")
        if entry.identifier and entry.identifier not in title:
            lines.append(f"   ID：{entry.identifier}")
        lines.append(f"   來源：{entry.url}")
    return "\n".join(lines)


def _get_public_cctv_page_url() -> str:
    explicit = os.getenv("CCTV_PAGE_URL")
    if explicit:
        return explicit

    base_url = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
    if base_url:
        return f"{base_url}/cctv.html"

    host = os.getenv("PUBLIC_HOST") or os.getenv("HOST", "localhost")
    port = os.getenv("PUBLIC_PORT") or os.getenv("PORT", "8000")
    port_text = f":{port}" if port not in ("80", "443") else ""
    scheme = "https" if port == "443" else "http"
    return f"{scheme}://{host}{port_text}/cctv.html"


def _reply_with_entries(
    event: MessageEvent,
    line_bot_api: LineBotApi,
    entries: Sequence[CCTVEntry],
    distances: Optional[Sequence[float]] = None,
) -> None:
    text = _format_entries(entries, distances)
    link_text = f"查看更多 CCTV：{_get_public_cctv_page_url()}"
    line_bot_api.reply_message(
        event.reply_token,
        [
            TextSendMessage(text=text),
            TextSendMessage(text=link_text),
        ],
    )
    set_topic(CHECK_CCTV_TOPIC)


def _ensure_data_ready(event: MessageEvent, line_bot_api: LineBotApi) -> bool:
    if _CCTV_ENTRIES:
        return True

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text="CCTV 資料尚未準備完成，請稍後再試。"),
    )
    return False


def _haversine(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    to_rad = math.radians
    lon1_r, lat1_r, lon2_r, lat2_r = map(to_rad, [lon1, lat1, lon2, lat2])
    dlon = lon2_r - lon1_r
    dlat = lat2_r - lat1_r
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlon / 2) ** 2
    c = 2 * math.asin(math.sqrt(a))
    return 6371000 * c


def _find_nearest_entries(longitude: float, latitude: float, limit: int = 3) -> List[Tuple[CCTVEntry, float]]:
    results: List[Tuple[CCTVEntry, float]] = []
    for entry in _CCTV_ENTRIES:
        dist = _haversine(longitude, latitude, entry.longitude, entry.latitude)
        results.append((entry, dist))
    results.sort(key=lambda item: item[1])
    return results[:limit]


def _search_by_name(keyword: str, limit: int = 5) -> List[CCTVEntry]:
    normalized = _normalize_for_match(keyword)
    tokens = _tokenize_keywords(keyword)
    if not normalized and not tokens:
        return []
    matches: List[Tuple[Tuple[int, int], CCTVEntry]] = []
    for entry in _CCTV_ENTRIES:
        score = _compute_name_score(entry, normalized, tokens)
        if score is not None:
            matches.append((score, entry))
    matches.sort(key=lambda item: item[0])
    return [entry for _, entry in matches[:limit]]


def _compute_name_score(
    entry: CCTVEntry,
    normalized_query: str,
    tokens: Sequence[str],
) -> Optional[Tuple[int, int]]:
    if normalized_query and normalized_query == entry.normalized_name:
        return (0, 0)
    if normalized_query and normalized_query == entry.normalized_id:
        return (0, 1)
    if normalized_query and normalized_query in entry.normalized_name:
        return (1, entry.normalized_name.index(normalized_query))
    if normalized_query and normalized_query in entry.normalized_id:
        return (2, entry.normalized_id.index(normalized_query))

    if tokens and _matches_tokens(entry, tokens):
        return (3, len(tokens))
    return None


def _matches_tokens(entry: CCTVEntry, tokens: Sequence[str]) -> bool:
    for token in tokens:
        if not token:
            continue
        in_name = token in entry.normalized_name
        in_id = token in entry.normalized_id
        in_area = any(token in area for area in entry.area_tokens)
        if not (in_name or in_id or in_area):
            return False
    return True


def _search_by_district(keyword: str, limit: int = 10) -> List[CCTVEntry]:
    tokens = _tokenize_keywords(keyword)
    if not tokens:
        return []
    matches = [entry for entry in _CCTV_ENTRIES if _matches_tokens(entry, tokens)]
    matches.sort(key=lambda item: item.display_name)
    return matches[:limit]


def _parse_coordinate_text(text: str) -> Tuple[Optional[float], Optional[float]]:
    sanitized = (
        text.replace("，", ",")
        .replace("；", ",")
        .replace("、", ",")
        .replace("：", ",")
        .replace(" ", "")
    )
    numbers = _COORD_PATTERN.findall(sanitized)
    if len(numbers) < 2:
        return None, None
    try:
        lon = float(numbers[0])
        lat = float(numbers[1])
        return lon, lat
    except ValueError:
        return None, None


def _handle_coordinate_query(event: MessageEvent, line_bot_api: LineBotApi, longitude: float, latitude: float) -> bool:
    if not _ensure_data_ready(event, line_bot_api):
        return True

    results = _find_nearest_entries(longitude, latitude)
    if not results:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="找不到附近的 CCTV。"),
        )
        return True

    entries, distances = zip(*results)
    _reply_with_entries(event, line_bot_api, entries, distances)
    return True


def _handle_name_query(event: MessageEvent, line_bot_api: LineBotApi, keyword: str) -> bool:
    if not _ensure_data_ready(event, line_bot_api):
        return True

    entries = _search_by_name(keyword)
    _reply_with_entries(event, line_bot_api, entries)
    return True


def _handle_district_query(event: MessageEvent, line_bot_api: LineBotApi, keyword: str) -> bool:
    if not _ensure_data_ready(event, line_bot_api):
        return True

    entries = _search_by_district(keyword)
    _reply_with_entries(event, line_bot_api, entries)
    return True


def handle_message_event(event: MessageEvent, line_bot_api: LineBotApi) -> bool:
    incoming_text = (event.message.text or "").strip()
    if not incoming_text:
        return False

    source = _source_key(event)

    if incoming_text in _TRIGGERS:
        set_topic(CHECK_CCTV_TOPIC)
        _SESSIONS.pop(source, None)
        line_bot_api.reply_message(event.reply_token, _build_entry_message())
        return True

    if incoming_text in _CANCEL_KEYWORDS:
        if _SESSIONS.pop(source, None):
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="已取消 CCTV 查詢。"))
            set_topic(None)
            return True
        return False

    if incoming_text in _MODE_LABELS:
        set_topic(CHECK_CCTV_TOPIC)
        session = Session(mode=_MODE_LABELS[incoming_text], stage="awaiting_input")
        _SESSIONS[source] = session
        if session.mode == "coordinate":
            line_bot_api.reply_message(event.reply_token, _coordinate_prompt())
        elif session.mode == "name":
            line_bot_api.reply_message(event.reply_token, _name_prompt())
        elif session.mode == "district":
            line_bot_api.reply_message(event.reply_token, _district_prompt())
        return True

    if get_topic() != CHECK_CCTV_TOPIC:
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

    if session.mode == "name":
        return _handle_name_query(event, line_bot_api, incoming_text)

    if session.mode == "district":
        return _handle_district_query(event, line_bot_api, incoming_text)

    return False


def handle_location_message(event: MessageEvent, line_bot_api: LineBotApi) -> bool:
    source = _source_key(event)
    session = _SESSIONS.get(source)
    if not session or session.mode != "coordinate":
        return False
    return _handle_coordinate_query(event, line_bot_api, event.message.longitude, event.message.latitude)


__all__ = [
    "handle_message_event",
    "handle_location_message",
    "CHECK_CCTV_TOPIC",
]
