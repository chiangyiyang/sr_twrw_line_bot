"""Quick reply demo topic helpers."""
from __future__ import annotations

from typing import Dict
from urllib.parse import parse_qs

from linebot import LineBotApi
from linebot.models import (
    CameraAction,
    CameraRollAction,
    DatetimePickerAction,
    LocationAction,
    MessageAction,
    MessageEvent,
    PostbackAction,
    PostbackEvent,
    QuickReply,
    QuickReplyButton,
    TextSendMessage,
    URIAction,
)

from .state import get_topic, set_topic


DEMO_QUICK_REPLY_TOPIC = "Demo quick replies"
DEMO_QUICK_REPLY_TOPIC_KEY = "demo_quick_replies"

_QUICK_REPLY_ITEMS = [
    {
        "label": "文字訊息",
        "icon": "https://scdn.line-apps.com/n/channel_devcenter/img/fx/01_2_restaurant.png",
        "action": MessageAction(label="文字訊息", text="示範：文字訊息"),
        "ack_text": "您選擇了 文字訊息（MessageAction）",
    },
    {
        "label": "資料回傳",
        "icon": "https://scdn.line-apps.com/n/channel_devcenter/img/fx/01_1_cafe.png",
        "action": PostbackAction(
            label="資料回傳",
            data=f"topic={DEMO_QUICK_REPLY_TOPIC_KEY}&choice=資料回傳",
            display_text="示範：資料回傳",
        ),
        "ack_text": "您選擇了 資料回傳（PostbackAction）",
        "postback_choice": "資料回傳",
    },
    {
        "label": "日期時間",
        "icon": "https://scdn.line-apps.com/n/channel_devcenter/img/fx/02_1_birthday.png",
        "action": DatetimePickerAction(
            label="日期時間",
            data=f"topic={DEMO_QUICK_REPLY_TOPIC_KEY}&choice=日期時間",
            mode="datetime",
        ),
        "ack_text": "您選擇了 日期時間（DatetimePickerAction）",
        "postback_choice": "日期時間",
    },
    {
        "label": "開啟連結",
        "icon": "https://scdn.line-apps.com/n/channel_devcenter/img/fx/02_2_question.png",
        "action": URIAction(label="開啟連結", uri="https://example.com"),
    },
    {
        "label": "開啟相機",
        "icon": "https://scdn.line-apps.com/n/channel_devcenter/img/fx/03_1_movie.png",
        "action": CameraAction(label="開啟相機"),
    },
    {
        "label": "相簿照片",
        "icon": "https://scdn.line-apps.com/n/channel_devcenter/img/fx/03_2_music.png",
        "action": CameraRollAction(label="相簿照片"),
    },
    {
        "label": "分享位置",
        "icon": "https://scdn.line-apps.com/n/channel_devcenter/img/fx/04_1_tap.png",
        "action": LocationAction(label="分享位置"),
    },
]

_MESSAGE_ACTION_RESPONSES: Dict[str, str] = {
    item["action"].text: item["ack_text"]
    for item in _QUICK_REPLY_ITEMS
    if isinstance(item["action"], MessageAction) and item.get("ack_text")
}

_POSTBACK_RESPONSE_BY_CHOICE: Dict[str, str] = {
    item["postback_choice"]: item["ack_text"]
    for item in _QUICK_REPLY_ITEMS
    if item.get("postback_choice")
}


def build_quick_reply_message() -> TextSendMessage:
    """Construct a quick reply menu demonstrating supported action types."""
    quick_reply = QuickReply(
        items=[
            QuickReplyButton(
                action=item["action"],
                image_url=item.get("icon"),
            )
            for item in _QUICK_REPLY_ITEMS
        ]
    )
    return TextSendMessage(
        text="這是 LINE 快速回覆動作示範，請選擇一個項目。",
        quick_reply=quick_reply,
    )


def handle_message_event(event: MessageEvent, line_bot_api: LineBotApi) -> bool:
    """Handle text messages related to the quick reply demo."""
    incoming_text = (event.message.text or "").strip()

    if incoming_text == DEMO_QUICK_REPLY_TOPIC:
        set_topic(DEMO_QUICK_REPLY_TOPIC)
        line_bot_api.reply_message(
            event.reply_token,
            build_quick_reply_message(),
        )
        return True

    if get_topic() != DEMO_QUICK_REPLY_TOPIC:
        return False

    if incoming_text in _MESSAGE_ACTION_RESPONSES:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=_MESSAGE_ACTION_RESPONSES[incoming_text]),
        )
        return True

    return False


def handle_postback_event(event: PostbackEvent, line_bot_api: LineBotApi) -> bool:
    """Handle postback responses triggered by the quick reply demo."""
    data = event.postback.data or ""
    if not data:
        return False

    params = parse_qs(data)
    topic = params.get("topic", [""])[0]
    choice = params.get("choice", [""])[0]

    if topic != DEMO_QUICK_REPLY_TOPIC_KEY or not choice:
        return False

    set_topic(DEMO_QUICK_REPLY_TOPIC)

    base_text = _POSTBACK_RESPONSE_BY_CHOICE.get(choice, f"您選擇了 {choice}")
    time_suffix = ""
    if event.postback.params:
        if "datetime" in event.postback.params:
            time_suffix = f"（時間：{event.postback.params['datetime']}）"
        elif "date" in event.postback.params:
            time_suffix = f"（日期：{event.postback.params['date']}）"
        elif "time" in event.postback.params:
            time_suffix = f"（時間：{event.postback.params['time']}）"

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=f"{base_text}{time_suffix}"),
    )
    return True
