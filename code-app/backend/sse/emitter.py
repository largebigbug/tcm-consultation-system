# -*- coding: utf-8 -*-
"""批次 5 AI 编排层的 SSE 事件发射器（契约 §3.3）。

唯一职责：把 (事件类型, data) 序列化为契约规定的分片格式
`event: <type>\ndata: <json>\n\n`，并给出响应头。事件类型不做业务加工。
"""
import json

# 契约 §3.3 的七类事件（其余类型一律视为编排层 bug，直接抛错暴露）
EVENT_TYPES = (
    "message_start",
    "delta",
    "tool_call",
    "tool_result",
    "render_payload",
    "message_end",
    "error",
)

MIME = "text/event-stream; charset=utf-8"


def format_event(event_type, data=None):
    """单条 SSE 分片：`event: <type>\\ndata: <json>\\n\\n`。"""
    if event_type not in EVENT_TYPES:
        raise ValueError("未定义的 SSE 事件类型：%s" % event_type)
    body = json.dumps(data if data is not None else {}, ensure_ascii=False)
    return "event: %s\ndata: %s\n\n" % (event_type, body)


def encode(events):
    """把 (类型, data) 序列迭代为 SSE 分片字符串，供 Flask Response 流式返回。"""
    for event_type, data in events:
        yield format_event(event_type, data)


def headers():
    """契约 §3.2 规定的响应头（含反代理缓冲关闭）。"""
    return {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    }
