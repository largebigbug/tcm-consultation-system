# -*- coding: utf-8 -*-
"""批次 5 AI 编排层（契约 docs/批次5-实现契约.md）。

模块边界：
  ai.orchestrator    对话编排：把 provider 的 Chunk 流转成契约 §3.3 的 SSE 事件序列并写审计
  ai.prompt_builder  system prompt 五要素构建（契约 §6）
  ai.tool_registry   工具 schema 生成 / 权限过滤 / 执行（契约 §4）
  ai.providers       provider 抽象与实现（deepseek / mock，契约 §5）
  sse.emitter        SSE 分片格式与响应头（契约 §3.3）
  sql_readonly       只读 SQL 守卫与受限执行（契约 §7）
"""
from ai.providers import get_provider, load_ai_config, status_payload

__all__ = ["get_provider", "load_ai_config", "status_payload"]
