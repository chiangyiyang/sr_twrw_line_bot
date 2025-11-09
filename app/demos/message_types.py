"""Message type demo topic helpers."""
from __future__ import annotations

from typing import Callable, Dict, List

from linebot import LineBotApi
from linebot.models import (
    AudioSendMessage,
    BaseSize,
    ButtonsTemplate,
    FlexSendMessage,
    ImagemapArea,
    ImagemapSendMessage,
    ImageSendMessage,
    LocationSendMessage,
    MessageAction,
    MessageEvent,
    MessageImagemapAction,
    QuickReply,
    QuickReplyButton,
    SendMessage,
    StickerSendMessage,
    TemplateSendMessage,
    TextSendMessage,
    URIAction,
    URIImagemapAction,
    VideoSendMessage,
)

from .. import state


DEMO_MESSAGE_TYPES_TOPIC = "Demo message types"


def _source_key(event: MessageEvent) -> str:
    source = event.source
    if getattr(source, "user_id", None):
        return f"user:{source.user_id}"
    if getattr(source, "group_id", None):
        return f"group:{source.group_id}"
    if getattr(source, "room_id", None):
        return f"room:{source.room_id}"
    return "unknown"


def _intro_text(message: str) -> TextSendMessage:
    return TextSendMessage(text=message)


def _build_text_demo() -> List[SendMessage]:
    return [
        _intro_text("這是一則文字訊息示範。"),
    ]


def _build_sticker_demo() -> List[SendMessage]:
    return [
        _intro_text("這是貼圖訊息示範。"),
        StickerSendMessage(package_id="11537", sticker_id="52002734"),
    ]


def _build_image_demo() -> List[SendMessage]:
    image_url = "https://scdn.line-apps.com/n/channel_devcenter/img/fx/01_5_carousel.png"
    return [
        _intro_text("這是圖片訊息示範。"),
        ImageSendMessage(original_content_url=image_url, preview_image_url=image_url),
    ]


def _build_video_demo() -> List[SendMessage]:
    video_url = "https://scdn.line-apps.com/n/channel_devcenter/img/core/linevideo.mp4"
    preview_image_url = "https://scdn.line-apps.com/n/channel_devcenter/img/core/linevideo_preview.jpg"
    return [
        _intro_text("這是影片訊息示範。"),
        VideoSendMessage(
            original_content_url=video_url,
            preview_image_url=preview_image_url,
        ),
    ]


def _build_audio_demo() -> List[SendMessage]:
    audio_url = "https://scdn.line-apps.com/n/channel_devcenter/img/core/voice/line_girl.mp3"
    return [
        _intro_text("這是語音訊息示範。"),
        AudioSendMessage(original_content_url=audio_url, duration=24000),
    ]


def _build_location_demo() -> List[SendMessage]:
    return [
        _intro_text("這是位置訊息示範。"),
        LocationSendMessage(
            title="LINE 台北辦公室",
            address="110 台北市信義區基隆路一段 200 號",
            latitude=25.033968,
            longitude=121.562283,
        ),
    ]


def _build_imagemap_demo() -> List[SendMessage]:
    base_url = "https://scdn.line-apps.com/n/channel_devcenter/img/imagemap/base"
    return [
        _intro_text("這是互動圖片訊息（Imagemap）示範。"),
        ImagemapSendMessage(
            base_url=base_url,
            alt_text="Imagemap 示範",
            base_size=BaseSize(height=1040, width=1040),
            actions=[
                URIImagemapAction(
                    link_uri="https://example.com",
                    area=ImagemapArea(x=0, y=0, width=520, height=1040),
                ),
                MessageImagemapAction(
                    text="Imagemap 點擊訊息",
                    area=ImagemapArea(x=520, y=0, width=520, height=1040),
                ),
            ],
        ),
    ]


def _build_template_demo() -> List[SendMessage]:
    template = ButtonsTemplate(
        title="Buttons Template 示範",
        text="請選擇一個動作",
        actions=[
            MessageAction(label="顯示訊息", text="Buttons Template：顯示訊息"),
            URIAction(label="造訪 LINE", uri="https://line.me"),
        ],
    )
    return [
        _intro_text("這是樣板訊息（Template）示範。"),
        TemplateSendMessage(alt_text="Buttons Template", template=template),
    ]


def _build_flex_demo() -> List[SendMessage]:
    container_bubble = {
        "type": "bubble",
        "header": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {"type": "text", "text": "Container", "size": "sm", "color": "#aaaaaa"},
                {"type": "text", "text": "Flex 容器類型", "weight": "bold", "size": "xl"},
            ],
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "md",
            "contents": [
                {
                    "type": "box",
                    "layout": "baseline",
                    "spacing": "sm",
                    "contents": [
                        {"type": "text", "text": "bubble", "flex": 2, "weight": "bold", "color": "#444444"},
                        {
                            "type": "text",
                            "text": "單一版面，適合呈現焦點資訊與互動動作",
                            "size": "sm",
                            "wrap": True,
                            "color": "#777777",
                            "flex": 5,
                        },
                    ],
                },
                {
                    "type": "box",
                    "layout": "baseline",
                    "spacing": "sm",
                    "contents": [
                        {"type": "text", "text": "carousel", "flex": 2, "weight": "bold", "color": "#444444"},
                        {
                            "type": "text",
                            "text": "多個 bubble 組成，可滑動切換多個商品或步驟",
                            "size": "sm",
                            "wrap": True,
                            "color": "#777777",
                            "flex": 5,
                        },
                    ],
                },
                {"type": "separator"},
                {
                    "type": "text",
                    "text": "容器決定 Flex Message 的載體與互動邏輯。",
                    "size": "sm",
                    "wrap": True,
                },
            ],
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "button",
                    "style": "primary",
                    "action": {
                        "type": "uri",
                        "label": "容器說明",
                        "uri": "https://developers.line.biz/en/docs/messaging-api/using-flex-messages/#flex-message-container",
                    },
                }
            ],
        },
    }

    block_bubble = {
        "type": "bubble",
        "header": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {"type": "text", "text": "Block", "size": "sm", "color": "#aaaaaa"},
                {"type": "text", "text": "版面區塊", "weight": "bold", "size": "xl"},
            ],
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "md",
            "contents": [
                {
                    "type": "box",
                    "layout": "baseline",
                    "contents": [
                        {"type": "text", "text": "header", "flex": 2, "color": "#555555"},
                        {"type": "text", "text": "呈現標題、階段或狀態列", "flex": 5, "size": "sm", "wrap": True},
                    ],
                },
                {
                    "type": "box",
                    "layout": "baseline",
                    "contents": [
                        {"type": "text", "text": "hero", "flex": 2, "color": "#555555"},
                        {"type": "text", "text": "大圖或影片吸引目光", "flex": 5, "size": "sm", "wrap": True},
                    ],
                },
                {
                    "type": "box",
                    "layout": "baseline",
                    "contents": [
                        {"type": "text", "text": "body", "flex": 2, "color": "#555555"},
                        {"type": "text", "text": "主要敘述、欄位與列表", "flex": 5, "size": "sm", "wrap": True},
                    ],
                },
                {
                    "type": "box",
                    "layout": "baseline",
                    "contents": [
                        {"type": "text", "text": "footer", "flex": 2, "color": "#555555"},
                        {"type": "text", "text": "操作按鈕或補充資訊", "flex": 5, "size": "sm", "wrap": True},
                    ],
                },
                {"type": "separator"},
                {
                    "type": "text",
                    "text": "亦可利用 styles 統一背景與字色。",
                    "size": "sm",
                    "wrap": True,
                },
            ],
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "button",
                    "style": "link",
                    "height": "sm",
                    "action": {
                        "type": "uri",
                        "label": "Block 範例",
                        "uri": "https://developers.line.biz/en/docs/messaging-api/using-flex-messages/#bubble",
                    },
                }
            ],
        },
    }

    component_bubble = {
        "type": "bubble",
        "header": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {"type": "text", "text": "Component", "size": "sm", "color": "#aaaaaa"},
                {"type": "text", "text": "元件組合", "weight": "bold", "size": "xl"},
            ],
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "md",
            "contents": [
                {"type": "text", "text": "常見元件：", "size": "sm"},
                {
                    "type": "box",
                    "layout": "vertical",
                    "spacing": "sm",
                    "contents": [
                        {"type": "text", "text": "• text / span：呈現標題與段落", "size": "sm", "wrap": True},
                        {"type": "text", "text": "• image / icon：圖片與圖示", "size": "sm", "wrap": True},
                        {"type": "text", "text": "• button / link：行動按鈕", "size": "sm", "wrap": True},
                        {"type": "text", "text": "• box：彈性排版容器", "size": "sm", "wrap": True},
                        {"type": "text", "text": "• separator / spacer / filler：分隔與留白", "size": "sm", "wrap": True},
                    ],
                },
                {"type": "separator"},
                {
                    "type": "button",
                    "style": "secondary",
                    "action": {
                        "type": "uri",
                        "label": "查看所有元件",
                        "uri": "https://developers.line.biz/en/docs/messaging-api/using-flex-messages/#component",
                    },
                },
            ],
        },
    }

    flex_contents = {
        "type": "carousel",
        "contents": [container_bubble, block_bubble, component_bubble],
    }
    return [
        _intro_text("以下示範 Flex Message 的 Container、Block 與 Component 結構。"),
        FlexSendMessage(alt_text="Flex Message 結構示範", contents=flex_contents),
    ]


_OPTION_BUILDERS: Dict[str, Callable[[], List[SendMessage]]] = {
    "訊息類型：文字": _build_text_demo,
    "訊息類型：貼圖": _build_sticker_demo,
    "訊息類型：圖片": _build_image_demo,
    "訊息類型：影片": _build_video_demo,
    "訊息類型：語音": _build_audio_demo,
    "訊息類型：位置": _build_location_demo,
    "訊息類型：互動圖片": _build_imagemap_demo,
    "訊息類型：樣板": _build_template_demo,
    "訊息類型：Flex": _build_flex_demo,
}

_QUICK_REPLY_ITEMS = [
    {
        "label": "文字",
        "text": "訊息類型：文字",
        "icon": "https://scdn.line-apps.com/n/channel_devcenter/img/fx/01_2_restaurant.png",
    },
    {
        "label": "貼圖",
        "text": "訊息類型：貼圖",
        "icon": "https://scdn.line-apps.com/n/channel_devcenter/img/sticker/01.png",
    },
    {
        "label": "圖片",
        "text": "訊息類型：圖片",
        "icon": "https://scdn.line-apps.com/n/channel_devcenter/img/fx/01_1_cafe.png",
    },
    {
        "label": "影片",
        "text": "訊息類型：影片",
        "icon": "https://scdn.line-apps.com/n/channel_devcenter/img/fx/03_1_movie.png",
    },
    {
        "label": "語音",
        "text": "訊息類型：語音",
        "icon": "https://scdn.line-apps.com/n/channel_devcenter/img/fx/03_2_music.png",
    },
    {
        "label": "位置",
        "text": "訊息類型：位置",
        "icon": "https://scdn.line-apps.com/n/channel_devcenter/img/fx/04_1_tap.png",
    },
    {
        "label": "互動圖片",
        "text": "訊息類型：互動圖片",
        "icon": "https://scdn.line-apps.com/n/channel_devcenter/img/fx/02_2_question.png",
    },
    {
        "label": "樣板",
        "text": "訊息類型：樣板",
        "icon": "https://scdn.line-apps.com/n/channel_devcenter/img/fx/02_1_birthday.png",
    },
    {
        "label": "Flex",
        "text": "訊息類型：Flex",
        "icon": "https://scdn.line-apps.com/n/channel_devcenter/img/fx/01_5_carousel.png",
    },
]


def build_message_types_quick_reply() -> TextSendMessage:
    """Construct quick reply menu listing available message type demos."""
    quick_reply = QuickReply(
        items=[
            QuickReplyButton(
                action=MessageAction(label=item["label"], text=item["text"]),
                image_url=item.get("icon"),
            )
            for item in _QUICK_REPLY_ITEMS
        ]
    )
    return TextSendMessage(
        text="這是 LINE 訊息類型示範，請挑選想體驗的訊息。",
        quick_reply=quick_reply,
    )


def handle_message_event(event: MessageEvent, line_bot_api: LineBotApi) -> bool:
    """Handle text messages related to the message type demo."""
    incoming_text = (event.message.text or "").strip()
    source = _source_key(event)

    if incoming_text == DEMO_MESSAGE_TYPES_TOPIC:
        state.set_topic(source, DEMO_MESSAGE_TYPES_TOPIC)
        line_bot_api.reply_message(
            event.reply_token,
            build_message_types_quick_reply(),
        )
        return True

    if state.get_topic(source) != DEMO_MESSAGE_TYPES_TOPIC:
        return False

    builder = _OPTION_BUILDERS.get(incoming_text)
    if builder is None:
        return False

    messages = builder()
    state.set_topic(source, DEMO_MESSAGE_TYPES_TOPIC)
    line_bot_api.reply_message(event.reply_token, messages)
    return True
