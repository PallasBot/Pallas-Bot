"""Legacy LLM chat 路径门禁（7.3：/ollama/* 与旧 envelope 隔离）。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from nonebot import logger

if TYPE_CHECKING:
    from .config import LlmConfig

LegacyChatRejectReason = Literal["legacy_chat_disabled", "legacy_ollama_blocked"]


def is_legacy_ollama_endpoint(endpoint: str) -> bool:
    return "/ollama/" in str(endpoint or "").strip().lower()


def assess_legacy_chat_submit(cfg: LlmConfig) -> LegacyChatRejectReason | None:
    if cfg.use_unified_chat_api:
        return None
    endpoint = str(cfg.legacy_chat_endpoint or "").strip()
    if is_legacy_ollama_endpoint(endpoint):
        if not cfg.legacy_chat_allowed:
            return "legacy_ollama_blocked"
        logger.warning("LLM legacy ollama endpoint 已显式放行（LLM_LEGACY_CHAT_ALLOWED）: {}", endpoint)
        return None
    if not cfg.legacy_chat_allowed:
        return "legacy_chat_disabled"
    logger.warning("LLM legacy chat endpoint was explicitly allowed: [{}]", endpoint)
    return None


def log_legacy_chat_config_warnings(cfg: LlmConfig) -> None:
    if cfg.use_unified_chat_api:
        return
    endpoint = str(cfg.legacy_chat_endpoint or "").strip()
    if is_legacy_ollama_endpoint(endpoint):
        if cfg.legacy_chat_allowed:
            logger.warning(
                "Legacy Ollama routing is running with unified chat disabled; migrate to the capability API: [{}]",
                endpoint,
            )
        else:
            logger.error(
                "Legacy Ollama routing is not allowed, so submission will be rejected: [{}]",
                endpoint,
            )
        return
    logger.warning(
        "Legacy submission was rejected because unified chat is disabled; enable it for migration: [{}]",
        endpoint or cfg.legacy_chat_endpoint,
    )
