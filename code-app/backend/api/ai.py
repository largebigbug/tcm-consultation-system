# -*- coding: utf-8 -*-
"""AI 对话 API（批次 5）：`/api/ai`。

契约 docs/批次5-实现契约.md §3：
  GET  /api/ai/status   登录即可，返回生效 provider/model 与启用态（未配置凭据时 enabled:false + 中文 hint）
  POST /api/ai/chat     登录即可，`text/event-stream` 流式返回契约 §3.3 的七类事件
未启用（口径 7）→ 503 + 中文 JSON（不进入 SSE）；参数非法 → 400；未登录 → 401（utils.security）。
"""
from flask import Blueprint, Response, g, request, stream_with_context

from ai import orchestrator
from ai.providers import load_ai_config, status_payload
from services import auth_service
from sse import emitter
from utils.response import fail, ok
from utils.security import login_required

bp = Blueprint("ai", __name__, url_prefix="/api/ai")

MAX_MESSAGE_CHARS = 2000

#: 生效配置可用的环境变量名（配置大模型页的启用指引；只暴露「名字」，不暴露取值）
ENV_KEYS = ("AI_PROVIDER", "AI_API_KEY", "AI_BASE_URL", "AI_MODEL")


@bp.get("/status")
@login_required
def ai_status():
    """生效态：provider / model 为**环境变量覆盖后**的实际取值（env > config.yaml）。"""
    return ok(status_payload())


@bp.post("/chat")
@login_required
def ai_chat():
    cfg = load_ai_config()
    if not cfg["enabled"]:
        return fail(cfg["hint"], "AI_DISABLED", 503)

    body = request.get_json(silent=True)
    if body is None:
        body = request.form.to_dict() if request.form else {}
    if not isinstance(body, dict):
        return fail("请求体必须为 JSON 对象", "INVALID_ARGUMENT", 400)
    message = body.get("message")
    if not isinstance(message, str) or not message.strip():
        return fail("消息内容不能为空", "INVALID_ARGUMENT", 400)
    message = message.strip()
    if len(message) > MAX_MESSAGE_CHARS:
        return fail("消息过长（上限 %d 字）" % MAX_MESSAGE_CHARS, "INVALID_ARGUMENT", 400)
    history = body.get("history")
    if history is not None and not isinstance(history, list):
        return fail("history 必须为消息数组", "INVALID_ARGUMENT", 400)
    context = body.get("context") or {}
    if not isinstance(context, dict):
        return fail("context 必须为对象", "INVALID_ARGUMENT", 400)

    user_id = getattr(g, "user_id", None)
    username = getattr(g, "username", None)

    def _events():
        for pair in orchestrator.run_chat(user_id, username, message, history, context, cfg):
            yield emitter.format_event(pair[0], pair[1])

    resp = Response(stream_with_context(_events()), content_type=emitter.MIME)
    for key, value in emitter.headers().items():
        resp.headers[key] = value
    return resp


@bp.get("/config")
@login_required
def ai_config():
    """「配置大模型」页（批次 6 契约 §5）：**仅管理员**、**只读**。

    返回生效 provider/model/base_url + 是否已配置凭据 + 环境变量名指引 + 中文 hint；
    **绝不回显任何凭据取值**（只回显「是否已配置」这一布尔事实）。
    """
    if "*" not in auth_service.get_permission_codes(getattr(g, "user_id", None)):
        return fail("仅管理员可查看大模型配置", "FORBIDDEN", 403)
    cfg = load_ai_config()
    if cfg["configured"]:
        hint = cfg["hint"]
    else:
        hint = ("%s；可在 backend/.env 或系统环境变量中设置 %s 后重启服务"
                % (cfg["hint"], "、".join(ENV_KEYS)))
    return ok({
        "provider": cfg["provider"],
        "model": cfg["model"],
        "base_url": cfg["base_url"],
        "configured": cfg["configured"],
        "enabled": cfg["enabled"],
        "envKeys": list(ENV_KEYS),
        "hint": hint,
    })
