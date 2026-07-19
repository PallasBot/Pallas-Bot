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
    logger.warning("LLM legacy chat endpoint 已显式放行（LLM_LEGACY_CHAT_ALLOWED）: {}", endpoint)
    return None


def log_legacy_chat_config_warnings(cfg: LlmConfig) -> None:
    if cfg.use_unified_chat_api:
        return
    endpoint = str(cfg.legacy_chat_endpoint or "").strip()
    if is_legacy_ollama_endpoint(endpoint):
        if cfg.legacy_chat_allowed:
            logger.warning(
                "LLM_USE_UNIFIED_CHAT_API=false 且 legacy 指向 ollama；仅过渡兼容，请尽快迁移统一 capability API: {}",
                endpoint,
            )
        else:
            logger.error(
                "LLM legacy 指向 /ollama/ 但未启用 LLM_LEGACY_CHAT_ALLOWED；提交将被拒绝: {}",
                endpoint,
            )
        return
    logger.warning(
        "LLM_USE_UNIFIED_CHAT_API=false；legacy 提交默认拒绝，过渡请设 LLM_LEGACY_CHAT_ALLOWED=true: {}",
        endpoint or cfg.legacy_chat_endpoint,
    )
