from __future__ import annotations

import json
from threading import Lock
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from pallas.core.foundation.config.repo_settings import repo_env_raw_value

_config_lock = Lock()
_cached_llm_config: LlmConfig | None = None


def _env_bool_first(keys: tuple[str, ...], default: bool) -> bool:
    resolved = _env_bool_first_optional(keys)
    if resolved is not None:
        return resolved
    return default


def _env_bool_first_optional(keys: tuple[str, ...]) -> bool | None:
    for key in keys:
        raw = repo_env_raw_value(key)
        if raw is not None:
            return raw.strip().lower() in ("1", "true", "yes", "on")
    return None


def resolve_llm_chat_enabled() -> bool:
    """全局 LLM 闲聊总闸：LLM_CHAT_ENABLED 优先，其次遗留 OLLAMA_ENABLE / LLM_CHAT_ENABLE。"""
    primary = _env_bool_first_optional(("LLM_CHAT_ENABLED", "OLLAMA_ENABLE"))
    if primary is not None:
        return primary
    legacy = _env_bool_first_optional(("LLM_CHAT_ENABLE",))
    if legacy is not None:
        return legacy
    return False


def resolve_legacy_rwkv_drunk_chat_enabled() -> bool:
    """遗留酒后 RWKV：仅当未显式配置 LLM_CHAT_ENABLED 时读取 CHAT_ENABLE / 插件 chat_enable。"""
    if _env_bool_first_optional(("LLM_CHAT_ENABLED",)) is not None:
        return False
    env_legacy = _env_bool_first_optional(("CHAT_ENABLE",))
    if env_legacy is not None:
        return env_legacy
    try:
        from packages.chat.config import get_chat_config

        return bool(get_chat_config().chat_enable)
    except Exception:
        return False


def _env_bool(key: str, default: bool = False) -> bool:
    raw = repo_env_raw_value(key)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_str(key: str, default: str = "") -> str:
    raw = repo_env_raw_value(key)
    if raw is None:
        return default
    return raw.strip()


def _env_int(key: str, default: int) -> int:
    raw = repo_env_raw_value(key)
    if raw is None:
        return default
    try:
        return int(raw.strip())
    except ValueError:
        return default


def _env_float(key: str, default: float) -> float:
    raw = repo_env_raw_value(key)
    if raw is None:
        return default
    try:
        return float(raw.strip())
    except ValueError:
        return default


def _parse_group_id_set(raw: str | None) -> list[int]:
    if not raw or not raw.strip():
        return []
    text = raw.strip()
    ids: set[int] = set()
    if text.startswith("["):
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return []
        if isinstance(data, list):
            for item in data:
                try:
                    ids.add(int(item))
                except (TypeError, ValueError):
                    continue
        return sorted(ids)
    for part in text.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ids.add(int(part))
        except ValueError:
            continue
    return sorted(ids)


def _env_group_id_list(key: str) -> list[int]:
    raw = repo_env_raw_value(key)
    if raw is None:
        return []
    return _parse_group_id_set(raw)


def resolve_llm_repeater_mode() -> str:
    raw = _env_str("LLM_REPEATER_MODE").strip().lower()
    if raw in ("off", "fallback", "polish", "both", "select", "select_fallback", "select_polish_lite"):
        return raw
    fallback = _env_bool("LLM_FALLBACK_ENABLED", False)
    polish = _env_bool("LLM_POLISH_ENABLED", True)
    if fallback and polish:
        return "both"
    if fallback:
        return "fallback"
    if polish:
        return "polish"
    return "select"


def resolve_llm_repeater_flags() -> tuple[bool, bool, bool]:
    mode = resolve_llm_repeater_mode()
    if mode == "off":
        return False, False, False
    if mode == "fallback":
        return True, False, False
    if mode == "polish":
        return False, True, False
    if mode == "both":
        return True, True, False
    if mode == "select":
        return False, False, True
    if mode == "select_fallback":
        return True, False, True
    if mode == "select_polish_lite":
        return False, False, True
    return False, False, True


def resolve_llm_polish_lite_enabled() -> bool:
    return resolve_llm_repeater_mode() == "select_polish_lite"


def resolve_conversation_feature_level_raw() -> str:
    raw = _env_str("CONVERSATION_FEATURE_LEVEL").strip().lower()
    if raw in ("legacy_repeater", "repeater_plus_decision", "full_conversation_kernel"):
        return raw
    return ""


VectorRetrieveMode = Literal["keyword", "embedding", "hybrid", "vector"]


def resolve_llm_vector_retrieve() -> VectorRetrieveMode:
    mode = _env_str("LLM_VECTOR_RETRIEVE", "hybrid").strip().lower()
    if mode in ("embedding", "hybrid", "vector"):
        return mode  # type: ignore[return-value]
    if mode == "keyword":
        return "keyword"
    return "hybrid"


def resolve_llm_embedding_model() -> str:
    raw = repo_env_raw_value("LLM_EMBEDDING_MODEL")
    text = str(raw or "stub").strip()
    return text or "stub"


class LlmMcpServerConfig(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    id: str
    transport: str = Field(default="stdio")
    command: list[str] = Field(default_factory=list)
    enabled_tools: list[str] = Field(default_factory=list)
    url: str = Field(default="")


class LlmConfig(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    ai_server_host: str = Field(default="127.0.0.1")
    ai_server_port: int = Field(default=9099, ge=1, le=65535)
    llm_chat_enabled: bool = Field(default=False)
    llm_repeater_mode: str = Field(default="select")
    llm_fallback_enabled: bool = Field(default=False)
    llm_polish_enabled: bool = Field(default=False)
    llm_select_enabled: bool = Field(default=True)
    llm_select_max_candidates: int = Field(default=12, ge=2, le=32)
    llm_polish_lite_enabled: bool = Field(default=False)
    llm_polish_lite_sample_rate: float = Field(default=0.12, ge=0.0, le=1.0)
    use_unified_chat_api: bool = Field(default=True)
    legacy_chat_allowed: bool = Field(default=False)
    legacy_chat_endpoint: str = Field(default="/api/llm/chat")
    legacy_del_session_endpoint: str = Field(default="/api/llm/del_session")
    unified_chat_endpoint: str = Field(default="/api/v1/chat/completions")
    unified_del_session_endpoint: str = Field(default="/api/v1/chat/completions/session")
    user_message_max_len: int = Field(default=4000, ge=64, le=16000)
    chat_timeout_sec: float = Field(default=30.0, ge=1.0, le=300.0)
    llm_session_enabled: bool = Field(default=True)
    llm_session_user_window: int = Field(default=18, ge=1, le=200)
    llm_session_group_window: int = Field(default=8, ge=0, le=100)
    llm_session_group_ambient_enabled: bool = Field(default=True)
    llm_session_user_ttl_sec: int = Field(default=0, ge=0, le=2592000)
    llm_session_private_ttl_sec: int = Field(default=259200, ge=0, le=2592000)
    llm_session_max_content_len: int = Field(default=4000, ge=64, le=16000)
    llm_session_strip_vision_enabled: bool = Field(default=True)
    llm_governance_enabled: bool = Field(default=True)
    llm_tools_enabled: bool = Field(default=True)
    llm_tools_selective: bool = Field(default=True)
    llm_chat_cooldown_sec: int = Field(default=3, ge=0, le=3600)
    llm_chat_max_concurrency: int = Field(default=2, ge=1, le=64)
    llm_chat_char_budget: int = Field(default=12000, ge=0, le=200000)
    llm_chat_disabled_group_ids: list[int] = Field(default_factory=list)
    llm_repeater_group_cooldown_sec: int = Field(default=60, ge=0, le=3600)
    llm_repeater_max_inflight: int = Field(default=1, ge=1, le=32)
    llm_repeater_global_rpm: int = Field(default=10, ge=1, le=600)
    llm_repeater_feedback_enabled: bool = Field(default=False)
    llm_repeater_bias_enabled: bool = Field(default=False)
    llm_repeater_writeback_enabled: bool = Field(default=False)
    conversation_feature_level: str = Field(default="")
    llm_reply_gate_enabled: bool = Field(default=True)
    llm_reply_gate_min_chars: int = Field(default=1, ge=0, le=32)
    llm_chat_queue_merge: bool = Field(default=True)
    llm_output_filter_enabled: bool = Field(default=True)
    llm_output_filter_chat_hard_phrases: list[str] = Field(default_factory=list)
    llm_output_filter_chat_soft_phrases: list[str] = Field(default_factory=list)
    llm_output_filter_polish_lite_hard_phrases: list[str] = Field(default_factory=list)
    llm_output_filter_polish_lite_soft_phrases: list[str] = Field(default_factory=list)
    llm_corpus_learn_guard_enabled: bool = Field(default=True)
    llm_corpus_cleanup_scheduled_enabled: bool = Field(default=True)
    llm_corpus_cleanup_interval_sec: int = Field(default=86400, ge=3600, le=604800)
    llm_corpus_cleanup_message_history_enabled: bool = Field(default=True)
    llm_tools_blacklist: list[str] = Field(default_factory=list)
    llm_tools_desc_max_len: int = Field(default=120, ge=32, le=512)
    llm_memory_rag_enabled: bool = Field(default=True)
    llm_vector_retrieve: VectorRetrieveMode = Field(default="hybrid")
    llm_embedding_model: str = Field(default="stub")
    llm_memory_rag_top_k: int = Field(default=3, ge=1, le=8)
    llm_memory_max_per_group: int = Field(default=200, ge=1, le=2000)
    llm_memory_content_max_len: int = Field(default=500, ge=64, le=4000)
    llm_memory_auto_episode_enabled: bool = Field(default=True)
    llm_memory_auto_episode_cooldown_sec: int = Field(default=120, ge=0, le=3600)
    llm_knowledge_sources_enabled: bool = Field(default=True)
    llm_knowledge_file_ingest_enabled: bool = Field(default=True)
    llm_knowledge_top_k: int = Field(default=3, ge=1, le=8)
    llm_knowledge_content_max_len: int = Field(default=400, ge=64, le=2000)
    llm_relationship_notes_enabled: bool = Field(default=True)
    llm_relationship_content_max_len: int = Field(default=200, ge=32, le=2000)
    llm_relationship_half_life_days: float = Field(default=30.0, ge=0.0, le=365.0)
    llm_relationship_min_weight: float = Field(default=0.2, ge=0.0, le=1.0)
    llm_session_summary_enabled: bool = Field(default=True)
    llm_session_summary_threshold: int = Field(default=40, ge=8, le=200)
    llm_session_summary_keep_messages: int = Field(default=16, ge=4, le=120)
    mcp_servers: list[LlmMcpServerConfig] = Field(default_factory=list)


def _env_str_list(key: str) -> list[str]:
    raw = repo_env_raw_value(key)
    if raw is None or not raw.strip():
        return []
    text = raw.strip()
    if text.startswith("["):
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return []
        if isinstance(data, list):
            return [str(item).strip() for item in data if str(item).strip()]
        return []
    return [part.strip() for part in text.replace(";", ",").split(",") if part.strip()]


def _env_str_list_or_default(key: str, default: tuple[str, ...]) -> list[str]:
    raw = repo_env_raw_value(key)
    if raw is None or not str(raw).strip():
        return list(default)
    return _env_str_list(key)


def _env_mcp_server_list(key: str) -> list[LlmMcpServerConfig]:
    raw = repo_env_raw_value(key)
    if raw is None or not raw.strip():
        return []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    items: list[LlmMcpServerConfig] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        try:
            items.append(LlmMcpServerConfig.model_validate(item))
        except Exception:
            continue
    return items


def get_llm_config() -> LlmConfig:
    global _cached_llm_config
    with _config_lock:
        if _cached_llm_config is not None:
            return _cached_llm_config
        host = _env_str("LLM_AI_SERVER_HOST") or _env_str("AI_SERVER_HOST") or "127.0.0.1"
        port = _env_int("LLM_AI_SERVER_PORT", _env_int("AI_SERVER_PORT", 9099))
        repeater_mode = resolve_llm_repeater_mode()
        fallback_enabled, polish_enabled, select_enabled = resolve_llm_repeater_flags()
        from pallas.product.llm.corpus_contamination import (
            CHAT_HARD_BLOCK_PHRASES,
            CHAT_SOFT_RETRY_PHRASES,
            POLISH_LITE_HARD_BLOCK_PHRASES,
            POLISH_LITE_SOFT_RETRY_PHRASES,
        )

        _cached_llm_config = LlmConfig(
            ai_server_host=host,
            ai_server_port=port,
            llm_chat_enabled=resolve_llm_chat_enabled(),
            llm_repeater_mode=repeater_mode,
            llm_fallback_enabled=fallback_enabled,
            llm_polish_enabled=polish_enabled,
            llm_select_enabled=select_enabled,
            llm_select_max_candidates=_env_int("LLM_SELECT_MAX_CANDIDATES", 12),
            llm_polish_lite_enabled=resolve_llm_polish_lite_enabled(),
            llm_polish_lite_sample_rate=_env_float("LLM_POLISH_LITE_SAMPLE_RATE", 0.12),
            use_unified_chat_api=_env_bool("LLM_USE_UNIFIED_CHAT_API", True),
            legacy_chat_allowed=_env_bool("LLM_LEGACY_CHAT_ALLOWED", False),
            legacy_chat_endpoint=_env_str("LLM_LEGACY_CHAT_ENDPOINT", "/api/llm/chat"),
            legacy_del_session_endpoint=_env_str("LLM_LEGACY_DEL_SESSION_ENDPOINT", "/api/llm/del_session"),
            unified_chat_endpoint=_env_str("LLM_UNIFIED_CHAT_ENDPOINT", "/api/v1/chat/completions"),
            unified_del_session_endpoint=_env_str(
                "LLM_UNIFIED_DEL_SESSION_ENDPOINT",
                "/api/v1/chat/completions/session",
            ),
            user_message_max_len=_env_int("LLM_USER_MESSAGE_MAX_LEN", 4000),
            chat_timeout_sec=_env_float("LLM_CHAT_TIMEOUT_SEC", 30.0),
            llm_session_enabled=_env_bool("LLM_SESSION_ENABLED", True),
            llm_session_user_window=_env_int("LLM_SESSION_USER_WINDOW", 18),
            llm_session_group_window=_env_int("LLM_SESSION_GROUP_WINDOW", 8),
            llm_session_group_ambient_enabled=_env_bool("LLM_SESSION_GROUP_AMBIENT_ENABLED", True),
            llm_session_user_ttl_sec=_env_int("LLM_SESSION_USER_TTL_SEC", 0),
            llm_session_private_ttl_sec=_env_int("LLM_SESSION_PRIVATE_TTL_SEC", 259200),
            llm_session_max_content_len=_env_int("LLM_SESSION_MAX_CONTENT_LEN", 4000),
            llm_session_strip_vision_enabled=_env_bool("LLM_SESSION_STRIP_VISION_ENABLED", True),
            llm_governance_enabled=_env_bool("LLM_GOVERNANCE_ENABLED", True),
            llm_tools_enabled=_env_bool("LLM_TOOLS_ENABLED", True),
            llm_tools_selective=_env_bool("LLM_TOOLS_SELECTIVE", True),
            llm_chat_cooldown_sec=_env_int("LLM_CHAT_COOLDOWN_SEC", 3),
            llm_chat_max_concurrency=_env_int("LLM_CHAT_MAX_CONCURRENCY", 2),
            llm_chat_char_budget=_env_int("LLM_CHAT_CHAR_BUDGET", 12000),
            llm_chat_disabled_group_ids=_env_group_id_list("LLM_CHAT_DISABLED_GROUP_IDS"),
            llm_repeater_group_cooldown_sec=_env_int("LLM_REPEATER_GROUP_COOLDOWN_SEC", 60),
            llm_repeater_max_inflight=_env_int("LLM_REPEATER_MAX_INFLIGHT", 1),
            llm_repeater_global_rpm=_env_int("LLM_REPEATER_GLOBAL_RPM", 10),
            llm_repeater_feedback_enabled=_env_bool("LLM_REPEATER_FEEDBACK_ENABLED", False),
            llm_repeater_bias_enabled=_env_bool("LLM_REPEATER_BIAS_ENABLED", False),
            llm_repeater_writeback_enabled=_env_bool("LLM_REPEATER_WRITEBACK_ENABLED", False),
            conversation_feature_level=resolve_conversation_feature_level_raw(),
            llm_reply_gate_enabled=_env_bool("LLM_REPLY_GATE_ENABLED", True),
            llm_reply_gate_min_chars=_env_int("LLM_REPLY_GATE_MIN_CHARS", 1),
            llm_chat_queue_merge=_env_bool("LLM_CHAT_QUEUE_MERGE", True),
            llm_output_filter_enabled=_env_bool("LLM_OUTPUT_FILTER_ENABLED", True),
            llm_output_filter_chat_hard_phrases=_env_str_list_or_default(
                "LLM_OUTPUT_FILTER_CHAT_HARD_PHRASES",
                CHAT_HARD_BLOCK_PHRASES,
            ),
            llm_output_filter_chat_soft_phrases=_env_str_list_or_default(
                "LLM_OUTPUT_FILTER_CHAT_SOFT_PHRASES",
                CHAT_SOFT_RETRY_PHRASES,
            ),
            llm_output_filter_polish_lite_hard_phrases=_env_str_list_or_default(
                "LLM_OUTPUT_FILTER_POLISH_LITE_HARD_PHRASES",
                POLISH_LITE_HARD_BLOCK_PHRASES,
            ),
            llm_output_filter_polish_lite_soft_phrases=_env_str_list_or_default(
                "LLM_OUTPUT_FILTER_POLISH_LITE_SOFT_PHRASES",
                POLISH_LITE_SOFT_RETRY_PHRASES,
            ),
            llm_corpus_learn_guard_enabled=_env_bool("LLM_CORPUS_LEARN_GUARD_ENABLED", True),
            llm_corpus_cleanup_scheduled_enabled=_env_bool("LLM_CORPUS_CLEANUP_SCHEDULED", True),
            llm_corpus_cleanup_interval_sec=_env_int("LLM_CORPUS_CLEANUP_INTERVAL_SEC", 86400),
            llm_corpus_cleanup_message_history_enabled=_env_bool(
                "LLM_CORPUS_CLEANUP_MESSAGE_HISTORY",
                True,
            ),
            llm_tools_blacklist=_env_str_list("LLM_TOOLS_BLACKLIST"),
            llm_tools_desc_max_len=_env_int("LLM_TOOLS_DESC_MAX_LEN", 120),
            llm_memory_rag_enabled=_env_bool("LLM_MEMORY_RAG_ENABLED", True),
            llm_vector_retrieve=resolve_llm_vector_retrieve(),
            llm_embedding_model=resolve_llm_embedding_model(),
            llm_memory_rag_top_k=_env_int("LLM_MEMORY_RAG_TOP_K", 3),
            llm_memory_max_per_group=_env_int("LLM_MEMORY_MAX_PER_GROUP", 200),
            llm_memory_content_max_len=_env_int("LLM_MEMORY_CONTENT_MAX_LEN", 500),
            llm_memory_auto_episode_enabled=_env_bool("LLM_MEMORY_AUTO_EPISODE_ENABLED", True),
            llm_memory_auto_episode_cooldown_sec=_env_int("LLM_MEMORY_AUTO_EPISODE_COOLDOWN_SEC", 120),
            llm_knowledge_sources_enabled=_env_bool("LLM_KNOWLEDGE_SOURCES_ENABLED", True),
            llm_knowledge_file_ingest_enabled=_env_bool("LLM_KNOWLEDGE_FILE_INGEST_ENABLED", True),
            llm_knowledge_top_k=_env_int("LLM_KNOWLEDGE_TOP_K", 3),
            llm_knowledge_content_max_len=_env_int("LLM_KNOWLEDGE_CONTENT_MAX_LEN", 400),
            llm_relationship_notes_enabled=_env_bool("LLM_RELATIONSHIP_NOTES_ENABLED", True),
            llm_relationship_content_max_len=_env_int("LLM_RELATIONSHIP_CONTENT_MAX_LEN", 200),
            llm_relationship_half_life_days=_env_float("LLM_RELATIONSHIP_HALF_LIFE_DAYS", 30.0),
            llm_relationship_min_weight=_env_float("LLM_RELATIONSHIP_MIN_WEIGHT", 0.2),
            llm_session_summary_enabled=_env_bool("LLM_SESSION_SUMMARY_ENABLED", True),
            llm_session_summary_threshold=_env_int("LLM_SESSION_SUMMARY_THRESHOLD", 40),
            llm_session_summary_keep_messages=_env_int("LLM_SESSION_SUMMARY_KEEP_MESSAGES", 16),
            mcp_servers=_env_mcp_server_list("LLM_MCP_SERVERS"),
        )
        return _cached_llm_config


def clear_llm_config_cache() -> None:
    global _cached_llm_config
    with _config_lock:
        _cached_llm_config = None
    try:
        from .governance import clear_llm_chat_governance_state

        clear_llm_chat_governance_state()
    except Exception:
        pass
    try:
        from .repeater_limit import clear_repeater_llm_limit_state

        clear_repeater_llm_limit_state()
    except Exception:
        pass


def llm_server_base_url(cfg: LlmConfig | None = None) -> str:
    c = cfg or get_llm_config()
    return f"http://{c.ai_server_host}:{c.ai_server_port}"
