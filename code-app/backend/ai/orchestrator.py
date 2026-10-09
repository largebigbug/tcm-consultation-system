# -*- coding: utf-8 -*-
"""对话编排层（契约 §3）：把 provider 的 Chunk 流编排成契约规定的 SSE 事件流。

一次对话的事件序列（契约 §3.3）：
    message_start → delta* → (tool_call → tool_result → render_payload|delta)* → message_end
异常时以 `error` 事件收尾（替代 render_payload/message_end）。

审计（契约 §8，写 `audit_logs`）：
    AI_CHAT       每次对话结束（messageId / questionLen / toolCallCount / provider）
    AI_TOOL_CALL  每次工具调用（含被拒）
    AI_SQL_QUERY  每次 SQL 只读调用（含被拒）
"""
import datetime
import json
import uuid

from services.auth_service import write_audit

from ai import prompt_builder, tool_registry
from ai.providers import ProviderError, get_provider, load_ai_config

MAX_TOOL_ROUNDS = 2
MAX_HISTORY_MESSAGES = 20          # ≤10 轮
MAX_HISTORY_CHARS = 2000


def _now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _clean_history(history):
    """只保留 user/assistant 文本消息，截断到最近 10 轮（契约 §3.2）。"""
    out = []
    for item in (history or [])[-MAX_HISTORY_MESSAGES:]:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content")
        if role not in ("user", "assistant") or not isinstance(content, str):
            continue
        out.append({"role": role, "content": content[:MAX_HISTORY_CHARS]})
    return out


def _audit_tool_call(user_id, username, chunk, outcome):
    detail = {
        "toolCallId": chunk.tool_call_id,
        "name": chunk.name,
        "arguments": chunk.arguments,
        "ok": bool(outcome.get("ok")),
        "summary": outcome.get("summary") or "",
    }
    if outcome.get("error"):
        detail["error"] = outcome["error"]
    write_audit(user_id, username, "AI_TOOL_CALL", json.dumps(detail, ensure_ascii=False))


def _audit_sql(user_id, username, outcome):
    sql_audit = outcome.get("sqlAudit")
    if not sql_audit:
        return
    detail = {"sql": sql_audit.get("sql") or "", "ok": bool(sql_audit.get("ok"))}
    if sql_audit.get("rejectedReason"):
        detail["rejectedReason"] = sql_audit["rejectedReason"]
    if sql_audit.get("rowCount") is not None:
        detail["rowCount"] = sql_audit["rowCount"]
    detail["elapsedMs"] = sql_audit.get("elapsedMs") or 0
    write_audit(user_id, username, "AI_SQL_QUERY", json.dumps(detail, ensure_ascii=False))


def run_chat(user_id, username, message, history=None, context=None, cfg=None):
    """编排一次对话，产出 (事件类型, data) 序列（契约 §3.3 的事件全集）。"""
    cfg = cfg or load_ai_config()
    message_id = uuid.uuid4().hex
    tool_call_count = 0
    finish_reason = "stop"
    yield ("message_start", {"messageId": message_id, "ts": _now()})
    try:
        provider = get_provider(cfg)
        if provider is None:
            raise ProviderError("未知的 ai.provider：%s" % cfg.get("provider"))
        tools = tool_registry.build_tools(user_id)
        prompt = prompt_builder.build_system_prompt(user_id, tools)
        messages = [{"role": "system", "content": prompt}]
        messages.extend(_clean_history(history))
        messages.append({"role": "user", "content": message})

        rounds = 0
        while True:
            rounds += 1
            calls = []
            for chunk in provider.chat(messages, tools):
                if chunk.type == "delta" and chunk.text:
                    yield ("delta", {"text": chunk.text})
                elif chunk.type == "tool_call":
                    calls.append(chunk)
                    yield ("tool_call", {"toolCallId": chunk.tool_call_id, "name": chunk.name,
                                         "arguments": chunk.arguments})
            if not calls or rounds >= MAX_TOOL_ROUNDS:
                break

            tool_messages = []
            for chunk in calls:
                tool_call_count += 1
                outcome = tool_registry.execute_tool(chunk.name, chunk.arguments,
                                                     user_id, username, cfg)
                result_data = {"toolCallId": chunk.tool_call_id, "ok": bool(outcome["ok"]),
                               "summary": outcome.get("summary") or ""}
                if outcome.get("rowsCount") is not None:
                    result_data["rowsCount"] = outcome["rowsCount"]
                if outcome.get("error"):
                    result_data["error"] = outcome["error"]
                yield ("tool_result", result_data)
                _audit_tool_call(user_id, username, chunk, outcome)
                _audit_sql(user_id, username, outcome)
                if outcome.get("ok") and outcome.get("renderType"):
                    yield ("render_payload", {"renderType": outcome["renderType"],
                                              "payload": outcome["payload"] or {}})
                else:
                    yield ("delta", {"text": "%s\n" % (outcome.get("summary") or "")})
                tool_messages.append({
                    "role": "tool",
                    "tool_call_id": chunk.tool_call_id,
                    "content": json.dumps({"ok": outcome.get("ok"),
                                           "summary": outcome.get("summary"),
                                           "error": outcome.get("error"),
                                           "rowsCount": outcome.get("rowsCount")},
                                          ensure_ascii=False),
                })

            if not provider.supports_tool_round:
                break
            messages.append({
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": c.tool_call_id, "type": "function",
                                "function": {"name": c.name,
                                             "arguments": json.dumps(c.arguments, ensure_ascii=False)}}
                               for c in calls],
            })
            messages.extend(tool_messages)

        yield ("message_end", {"finishReason": finish_reason, "toolCallCount": tool_call_count})
    except Exception as exc:                           # noqa: BLE001 - 统一转中文 error 事件
        finish_reason = "error"
        yield ("error", {"message": "AI 对话失败：%s" % exc, "code": "AI_ERROR"})
    finally:
        write_audit(user_id, username, "AI_CHAT", json.dumps({
            "messageId": message_id,
            "questionLen": len(message or ""),
            "toolCallCount": tool_call_count,
            "provider": cfg.get("provider"),
        }, ensure_ascii=False))
