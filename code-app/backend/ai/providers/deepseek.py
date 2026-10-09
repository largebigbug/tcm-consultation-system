# -*- coding: utf-8 -*-
"""DeepSeek provider（OpenAI 兼容的 function-calling 流式客户端）。

请求：`POST {base_url}/chat/completions`，`stream: true`，`tools` 为 function-calling schema。
仅用标准库 `urllib`（本项目 requirements 未装 requests），逐行解析 SSE：
  - `delta.content`            → Chunk.delta
  - `delta.tool_calls[i]`      → 累积（按 index 拼 name/arguments），流结束产出 Chunk.tool_call
拿到工具结果后 `supports_tool_round = True`，编排层会把工具结果回灌再要一次最终答复。
"""
import json
import urllib.error
import urllib.request

from ai.providers.base import BaseProvider, Chunk, ProviderError


class DeepSeekProvider(BaseProvider):

    name = "deepseek"
    supports_tool_round = True

    def __init__(self, model="deepseek-chat", api_key="", base_url="",
                 max_tokens=2048, timeout_seconds=30):
        BaseProvider.__init__(self, model=model or "deepseek-chat", api_key=api_key,
                              base_url=(base_url or "").rstrip("/"),
                              max_tokens=max_tokens, timeout_seconds=timeout_seconds)

    def _endpoint(self):
        return "%s/chat/completions" % (self.base_url or "https://api.deepseek.com")

    def _payload(self, messages, tools):
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "max_tokens": self.max_tokens,
        }
        if tools:
            # 归一化为协议规定的 {type, function}（丢弃内部便捷别名 `name` / `_meta`）
            payload["tools"] = [{"type": "function", "function": t["function"]}
                                for t in tools if (t or {}).get("function")]
            payload["tool_choice"] = "auto"
        return payload

    def chat(self, messages, tools=None):
        req = urllib.request.Request(
            self._endpoint(),
            data=json.dumps(self._payload(messages, tools), ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
                "Authorization": "Bearer %s" % self.api_key,
            },
            method="POST",
        )
        pending = {}                                   # index -> {id,name,arguments}
        order = []
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                for raw in resp:
                    line = raw.decode("utf-8", "replace").strip()
                    if not line or not line.startswith("data:"):
                        continue
                    body = line[5:].strip()
                    if body == "[DONE]":
                        break
                    try:
                        chunk = json.loads(body)
                    except ValueError:
                        continue
                    for choice in chunk.get("choices") or []:
                        delta = choice.get("delta") or {}
                        if delta.get("content"):
                            yield Chunk.delta(delta["content"])
                        for call in delta.get("tool_calls") or []:
                            idx = call.get("index", 0)
                            slot = pending.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                            if idx not in order:
                                order.append(idx)
                            if call.get("id"):
                                slot["id"] = call["id"]
                            fn = call.get("function") or {}
                            if fn.get("name"):
                                slot["name"] = fn["name"]
                            if fn.get("arguments"):
                                slot["arguments"] += fn["arguments"]
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", "replace")[:300]
            except Exception:                          # noqa: BLE001 - 错误详情尽力而为
                detail = ""
            raise ProviderError("模型服务返回错误（HTTP %s）：%s" % (exc.code, detail or exc.reason))
        except urllib.error.URLError as exc:
            raise ProviderError("无法连接模型服务（%s）：%s" % (self.base_url, exc.reason))
        except TimeoutError:
            raise ProviderError("模型服务响应超时（%s 秒）" % self.timeout_seconds)

        for idx in order:
            slot = pending[idx]
            if not slot.get("name"):
                continue
            try:
                arguments = json.loads(slot.get("arguments") or "{}")
            except ValueError:
                arguments = {"__raw__": slot.get("arguments")}
            if not isinstance(arguments, dict):
                arguments = {"value": arguments}
            yield Chunk.tool_call(slot["name"], arguments,
                                  tool_call_id=slot.get("id") or ("call_%d" % idx))
