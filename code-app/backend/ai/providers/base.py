# -*- coding: utf-8 -*-
"""provider 抽象（契约 §5）：`chat(messages, tools) -> Iterator[Chunk]`。

Chunk 只表达两类增量：`delta`（文本）与 `tool_call`（工具名 + 参数）；
编排层负责把 Chunk 翻译成 SSE 事件并执行工具。
"""
from dataclasses import dataclass, field


class ProviderError(RuntimeError):
    """模型调用失败（网络/鉴权/协议）；编排层会转成中文 `error` 事件。"""


@dataclass
class Chunk(object):
    type: str                                     # "delta" | "tool_call"
    text: str = ""
    tool_call_id: str = ""
    name: str = ""
    arguments: dict = field(default_factory=dict)

    @staticmethod
    def delta(text):
        return Chunk(type="delta", text=text)

    @staticmethod
    def tool_call(name, arguments, tool_call_id="call_0"):
        return Chunk(type="tool_call", name=name, arguments=arguments or {},
                     tool_call_id=tool_call_id)


class BaseProvider(object):
    """所有 provider 的基类；`supports_tool_round` 决定是否需要把工具结果回灌模型。"""

    name = "base"
    model = ""
    supports_tool_round = False

    def __init__(self, model="", api_key="", base_url="", max_tokens=2048, timeout_seconds=30):
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self.max_tokens = max_tokens
        self.timeout_seconds = timeout_seconds

    def chat(self, messages, tools=None):         # pragma: no cover - 抽象方法
        raise NotImplementedError
