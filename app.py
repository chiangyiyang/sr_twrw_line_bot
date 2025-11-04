import os
import sys
from urllib.parse import parse_qs

from flask import Flask, request, abort
from dotenv import load_dotenv

from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
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
    TextMessage,
    TextSendMessage,
    URIAction,
)


load_dotenv()

app = Flask(__name__)


CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")

if not CHANNEL_SECRET or not CHANNEL_ACCESS_TOKEN:
    print(
        "ERROR: Missing LINE credentials. Set LINE_CHANNEL_SECRET and LINE_CHANNEL_ACCESS_TOKEN.",
        file=sys.stderr,
    )

line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN) if CHANNEL_ACCESS_TOKEN else None
handler = WebhookHandler(CHANNEL_SECRET) if CHANNEL_SECRET else None


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


DEMO_QUICK_REPLY_TOPIC = "Demo quick replies"
DEMO_QUICK_REPLY_TOPIC_KEY = "demo_quick_replies"

current_topic = None

DEMO_QUICK_REPLY_ITEMS = [
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

DEMO_MESSAGE_ACTION_RESPONSES = {
    item["action"].text: item["ack_text"]
    for item in DEMO_QUICK_REPLY_ITEMS
    if isinstance(item["action"], MessageAction) and item.get("ack_text")
}

DEMO_POSTBACK_RESPONSE_BY_CHOICE = {
    item["postback_choice"]: item["ack_text"]
    for item in DEMO_QUICK_REPLY_ITEMS
    if item.get("postback_choice")
}


def _build_demo_quick_reply_message() -> TextSendMessage:
    """Build a quick reply message that showcases different action types."""
    quick_reply = QuickReply(
        items=[
            QuickReplyButton(
                action=item["action"],
                image_url=item.get("icon"),
            )
            for item in DEMO_QUICK_REPLY_ITEMS
        ]
    )
    return TextSendMessage(
        text="這是 LINE 快速回覆動作示範，請選擇一個項目。",
        quick_reply=quick_reply,
    )


@handler.add(MessageEvent, message=TextMessage)
def handle_text_message(event: MessageEvent):
    if line_bot_api is None:
        return

    incoming_text = (event.message.text or "").strip()

    if incoming_text == DEMO_QUICK_REPLY_TOPIC:
        global current_topic
        current_topic = DEMO_QUICK_REPLY_TOPIC
        line_bot_api.reply_message(
            event.reply_token,
            _build_demo_quick_reply_message(),
        )
        return

    if current_topic == DEMO_QUICK_REPLY_TOPIC and incoming_text in DEMO_MESSAGE_ACTION_RESPONSES:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=DEMO_MESSAGE_ACTION_RESPONSES[incoming_text]),
        )
        return

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=incoming_text),
    )


@handler.add(PostbackEvent)
def handle_postback_event(event: PostbackEvent):
    if line_bot_api is None:
        return

    data = event.postback.data or ""
    params = parse_qs(data)
    topic = params.get("topic", [""])[0]
    choice = params.get("choice", [""])[0]

    if topic == DEMO_QUICK_REPLY_TOPIC_KEY and choice:
        global current_topic
        current_topic = DEMO_QUICK_REPLY_TOPIC

        base_text = DEMO_POSTBACK_RESPONSE_BY_CHOICE.get(choice, f"您選擇了 {choice}")
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


def main():
    port = int(os.getenv("PORT", "8000"))
    host = os.getenv("HOST", "0.0.0.0")
    debug = os.getenv("FLASK_DEBUG", "0") == "1"
    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    main()
