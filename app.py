import os
import sys

from flask import Flask, abort, request, send_from_directory
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

import check_cctv
import check_rainfall
import find_location
import rainfall
import report_event
from report_event.api import api_bp as report_event_api_bp
from demos import message_types, quick_replies, state


load_dotenv()

app = Flask(__name__)
rainfall.init_app(app)
app.register_blueprint(report_event_api_bp)


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


@app.get("/rainfall.html")
def rainfall_page():
    return send_from_directory(app.root_path, "rainfall.html")


@app.get("/cctv.html")
def cctv_page():
    return send_from_directory(app.root_path, "cctv.html")


@app.get("/cctv.json")
def cctv_data():
    return send_from_directory(app.root_path, "cctv.json")


@app.get("/events.html")
def events_page():
    return send_from_directory(app.root_path, "events.html")


@app.get("/events/pictures/<path:filename>")
def event_picture(filename: str):
    pictures_dir = os.path.join(app.root_path, "events", "pictures")
    return send_from_directory(pictures_dir, filename)


@app.get("/events_admin.html")
def events_admin_page():
    return send_from_directory(app.root_path, "events_admin.html")


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


@handler.add(MessageEvent, message=TextMessage)
def handle_text_message(event: MessageEvent):
    print(f"Received message: {event.message.text}")
    if line_bot_api is None:
        return

    if check_rainfall.handle_message_event(event, line_bot_api):
        return

    if check_cctv.handle_message_event(event, line_bot_api):
        return

    if find_location.handle_message_event(event, line_bot_api):
        return

    if report_event.handle_message_event(event, line_bot_api):
        return

    if quick_replies.handle_message_event(event, line_bot_api):
        return

    if message_types.handle_message_event(event, line_bot_api):
        return

    current_topic = state.get_topic()
    state.set_topic(None)
    if current_topic is None:
        helper_quick_reply = QuickReply(
            items=[
                QuickReplyButton(action=MessageAction(label="查雨量", text="查雨量")),
                QuickReplyButton(action=MessageAction(label="里程轉座標", text="里程轉座標")),
                QuickReplyButton(action=MessageAction(label="座標轉里程", text="座標轉里程")),
                QuickReplyButton(action=MessageAction(label="CCTV", text="CCTV")),
                QuickReplyButton(action=MessageAction(label="回報事件", text="回報事件")),
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


@handler.add(PostbackEvent)
def handle_postback_event(event: PostbackEvent):
    if line_bot_api is None:
        return

    if quick_replies.handle_postback_event(event, line_bot_api):
        return


@handler.add(MessageEvent, message=LocationMessage)
def handle_location_message(event: MessageEvent):
    if line_bot_api is None:
        return

    if report_event.handle_location_message(event, line_bot_api):
        return

    if check_rainfall.handle_location_message(event, line_bot_api):
        return

    if check_cctv.handle_location_message(event, line_bot_api):
        return

    if find_location.handle_location_message(event, line_bot_api):
        return


@handler.add(MessageEvent, message=ImageMessage)
def handle_image_message(event: MessageEvent):
    if line_bot_api is None:
        return

    if report_event.handle_image_message(event, line_bot_api):
        return


def main():
    port = int(os.getenv("PORT", "8000"))
    host = os.getenv("HOST", "0.0.0.0")
    debug = os.getenv("FLASK_DEBUG", "0") == "1"
    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    main()
