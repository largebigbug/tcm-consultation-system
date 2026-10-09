# -*- coding: utf-8 -*-
"""provider 装配与生效配置解析（契约 §5 + 主代补充要求）。

生效配置的取值优先级：**环境变量 > config.yaml > 内置默认值**。
  `AI_PROVIDER`  → `ai.provider`
  `AI_API_KEY`   → `ai.api_key`（其次 `DEEPSEEK_API_KEY`，最后 config.yaml）
  `AI_BASE_URL`  → `ai.base_url`（空串按默认值处理）
  `AI_MODEL`     → `ai.model`（主代仅要求前 3 项；本项为对称补充，已在交付报告登记）

因此验收可在**不修改 config.yaml** 的前提下，用 `AI_PROVIDER=mock` 切到离线 provider。
"""
import os

from config import settings

from ai.providers.base import BaseProvider, Chunk, ProviderError
from ai.providers.deepseek import DeepSeekProvider
from ai.providers.mock import MockProvider

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"
DEFAULT_SQL_LIMITS = {"default_limit": 100, "max_limit": 500, "timeout_seconds": 3}

#: 契约 §3.1 的未配置凭据提示（逐字沿用，便于验收比对）
HINT_NOT_CONFIGURED = ("AI 对话未启用：请在 backend/.env 配置 DEEPSEEK_API_KEY"
                       "（或把 ai.provider 设为 mock 以离线演示）")

PROVIDERS = {"deepseek": DeepSeekProvider, "mock": MockProvider}


def _env(*names):
    for name in names:
        value = os.environ.get(name)
        if value is not None and str(value).strip() != "":
            return str(value).strip(), name
    return None, None


def load_ai_config():
    """返回生效配置（含 configured/enabled/hint 与生效来源），供 status 与装配共用。"""
    prov_env, prov_src = _env("AI_PROVIDER")
    key_env, key_src = _env("AI_API_KEY", "DEEPSEEK_API_KEY")
    url_env, url_src = _env("AI_BASE_URL")
    model_env, model_src = _env("AI_MODEL")

    provider = (prov_env or settings.get("ai.provider") or "deepseek").strip()
    if not prov_env:
        prov_src = "config.yaml"
    api_key = key_env or (settings.get("ai.api_key") or "")
    if not key_env:
        key_src = "config.yaml"
    base_url = (url_env or settings.get("ai.base_url") or "").strip() or DEFAULT_BASE_URL
    if not url_env:
        url_src = "config.yaml" if (settings.get("ai.base_url") or "").strip() else "默认值"
    model = (model_env or settings.get("ai.model") or "").strip() or DEFAULT_MODEL
    if not model_env:
        model_src = "config.yaml"

    switch_on = bool(settings.get("ai.enabled", False))
    known = provider in PROVIDERS
    configured = bool(api_key) if provider == "deepseek" else (provider == "mock")
    enabled = switch_on and known and configured

    if not known:
        hint = "AI 对话未启用：未知的 ai.provider「%s」（可选 deepseek / mock）" % provider
    elif not switch_on:
        hint = "AI 对话未启用：配置项 ai.enabled 为 false（设为 true 后重启服务即可）"
    elif not configured:
        hint = HINT_NOT_CONFIGURED
    else:
        hint = "AI 对话已启用（provider: %s，model: %s）" % (provider, model)

    limits = dict(DEFAULT_SQL_LIMITS)
    for key, value in (settings.get("ai.sql_limits", {}) or {}).items():
        limits[key] = value
    return {
        "enabled": enabled,
        "configured": configured,
        "switch_on": switch_on,
        "provider": provider,
        "model": model,
        "api_key": api_key,
        "base_url": base_url,
        "max_tokens": int(settings.get("ai.max_tokens", 2048) or 2048),
        "timeout_seconds": int(settings.get("ai.timeout_seconds", 30) or 30),
        "sql_limits": limits,
        "hint": hint,
        "sources": {"provider": prov_src, "api_key": key_src, "base_url": url_src,
                    "model": model_src},
    }


def status_payload():
    """`GET /api/ai/status` 的 data 段（契约 §3.1：恰好 5 个字段）。"""
    cfg = load_ai_config()
    return {
        "enabled": cfg["enabled"],
        "provider": cfg["provider"],
        "model": cfg["model"],
        "configured": cfg["configured"],
        "hint": cfg["hint"],
    }


def get_provider(cfg=None):
    """按生效配置装配 provider；未知 provider 返回 None（由调用方走降级口径）。"""
    cfg = cfg or load_ai_config()
    cls = PROVIDERS.get(cfg["provider"])
    if cls is None:
        return None
    if cfg["provider"] == "mock":
        return cls(model=cfg["model"])
    return cls(model=cfg["model"], api_key=cfg["api_key"], base_url=cfg["base_url"],
               max_tokens=cfg["max_tokens"], timeout_seconds=cfg["timeout_seconds"])


__all__ = ["BaseProvider", "Chunk", "ProviderError", "DeepSeekProvider", "MockProvider",
           "PROVIDERS", "load_ai_config", "status_payload", "get_provider",
           "DEFAULT_BASE_URL", "DEFAULT_MODEL", "HINT_NOT_CONFIGURED"]
