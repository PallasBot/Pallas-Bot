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
    """遗留酒后 RWKV（Bot 侧开关，推理仍打 AI 仓 POST /api/chat）。

    与 ``LLM_CHAT_ENABLED`` 独立：两者可同时开；醉酒提交时 LLM 优先，否则走 RWKV。
    开关来源：``CHAT_ENABLE``；兼容旧扩展插件 ``chat_enable``（若仍安装）。
    """
    import importlib

    env_legacy = _env_bool_first_optional(("CHAT_ENABLE",))
    if env_legacy is not None:
        return env_legacy
    for import_path in (
        "pallas_plugin_chat.config",
        "packages.chat.config",
    ):
        try:
            mod = importlib.import_module(import_path)
            getter = getattr(mod, "get_chat_config", None)
            if getter is None:
                continue
            return bool(getter().chat_enable)
        except Exception:
            continue
    return False


def resolve_chat_tts_enabled() -> bool:
    """酒后对话是否在出字后附带侧车 TTS。

    开关：``CHAT_TTS_ENABLE``。另需醉酒度 / 回文字数达到阈值，且「牛牛说」可用。
    """
    env_tts = _env_bool_first_optional(("CHAT_TTS_ENABLE",))
    if env_tts is not None:
        return env_tts
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


def resolve_conversation_feature_level_raw() -> str:
    raw = _env_str("CONVERSATION_FEATURE_LEVEL").strip().lower()
    if raw in ("legacy_repeater", "repeater_plus_decision", "full_conversation_kernel"):
        return raw
    return ""


VectorRetrieveMode = Literal["keyword", "embedding", "hybrid", "vector"]
LlmRuntime = Literal["bot_kernel"]


def resolve_llm_runtime() -> LlmRuntime:
    raw = _env_str("LLM_RUNTIME", "bot_kernel").strip().lower()
    if raw and raw != "bot_kernel":
        # 遗留 ai_service 已移除，强制走内核
        pass
    return "bot_kernel"


def resolve_llm_base_url() -> str:
    return _env_str("LLM_BASE_URL") or _env_str("LLM_REMOTE_BASE_URL") or ""


def resolve_llm_api_key() -> str:
    return _env_str("LLM_API_KEY") or _env_str("LLM_REMOTE_API_KEY") or ""


def resolve_llm_model() -> str:
    return _env_str("LLM_MODEL") or _env_str("LLM_REMOTE_MODEL") or ""


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


def resolve_llm_embedding_provider() -> str:
    from pallas.product.llm.knowledge.embedding_provider import normalize_embedding_provider_name

    return normalize_embedding_provider_name(str(repo_env_raw_value("LLM_EMBEDDING_PROVIDER") or ""))


class LlmMcpServerConfig(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    id: str
    transport: str = Field(default="stdio")
    command: list[str] = Field(default_factory=list)
    enabled_tools: list[str] = Field(default_factory=list)
    url: str = Field(default="")


class LlmConfig(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    llm_runtime: LlmRuntime = Field(default="bot_kernel")
    llm_base_url: str = Field(default="")
    llm_api_key: str = Field(default="")
    llm_model: str = Field(default="")
    llm_tools_max_rounds: int = Field(default=4, ge=1, le=16)
    ai_server_host: str = Field(default="127.0.0.1")
    ai_server_port: int = Field(default=9099, ge=1, le=65535)
    llm_chat_enabled: bool = Field(default=False)
    chat_tts_enable: bool = Field(default=False)
    drunk_tts_min_drunkenness: int = Field(default=1, ge=0, le=100)
    drunk_tts_min_chars: int = Field(default=6, ge=0, le=2000)
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
    llm_tools_soft_recall_enabled: bool = Field(default=True)
    llm_tools_soft_recall_min_score: int = Field(default=6, ge=1, le=32)
    llm_tools_soft_recall_max_candidates: int = Field(default=3, ge=1, le=8)
    llm_chat_cooldown_sec: int = Field(default=3, ge=0, le=3600)
    llm_chat_max_concurrency: int = Field(default=2, ge=1, le=64)
    llm_shared_max_concurrency: int = Field(default=4, ge=1, le=64)
    llm_chat_queue_enabled: bool = Field(default=True)
    llm_chat_queue_max: int = Field(default=8, ge=1, le=64)
    llm_chat_queue_wait_sec: float = Field(default=20.0, ge=0.1, le=120.0)
    llm_chat_char_budget: int = Field(default=12000, ge=0, le=200000)
    llm_chat_disabled_group_ids: list[int] = Field(default_factory=list)
    llm_repeater_feedback_enabled: bool = Field(default=True)
    llm_repeater_bias_enabled: bool = Field(default=True)
    llm_repeater_writeback_enabled: bool = Field(default=True)
    conversation_feature_level: str = Field(default="")
    llm_reply_gate_enabled: bool = Field(default=True)
    llm_current_turn_decision_enabled: bool = Field(default=False)
    llm_current_turn_decision_model: str = Field(default="")
    llm_reply_gate_min_chars: int = Field(default=1, ge=0, le=32)
    llm_chat_queue_merge: bool = Field(default=True)
    llm_output_filter_enabled: bool = Field(default=True)
    llm_output_filter_chat_hard_phrases: list[str] = Field(default_factory=list)
    llm_output_filter_chat_soft_phrases: list[str] = Field(default_factory=list)
    llm_persona_output_firewall: dict[str, object] = Field(default_factory=dict)
    llm_reply_postprocess_enabled: bool = Field(default=False)
    llm_reply_typo_enabled: bool = Field(default=False)
    llm_reply_typo_rate: float = Field(default=0.01, ge=0.0, le=1.0)
    llm_reply_trim_terminal_period_enabled: bool = Field(default=True)
    llm_reply_trim_terminal_period_rate: float = Field(default=0.9, ge=0.0, le=1.0)
    llm_reply_mention_cooldown_sec: int = Field(default=900, ge=0, le=86400)
    llm_sticker_fit_enabled: bool = Field(default=False)
    llm_chat_sticker_enabled: bool = Field(default=True)
    llm_chat_sticker_cooldown_sec: int = Field(default=90, ge=0, le=86400)
    llm_chat_sticker_max_per_hour: int = Field(default=8, ge=0, le=1000)
    llm_sticker_vision_enabled: bool = Field(default=False)
    llm_sticker_vision_candidate_count: int = Field(default=4, ge=3, le=6)
    llm_sticker_vision_timeout_sec: float = Field(default=15.0, ge=1.0, le=30.0)
    llm_sticker_vision_max_per_hour: int = Field(default=12, ge=0, le=1000)
    llm_sticker_label_backfill_enabled: bool = Field(default=True)
    llm_sticker_label_backfill_daily_limit: int = Field(default=200, ge=0, le=2000)
    llm_sticker_label_realtime_daily_limit: int = Field(default=300, ge=0, le=2000)
    llm_reply_effect_eval_enabled: bool = Field(default=False)
    llm_reply_style_variants: dict[str, object] = Field(default_factory=dict)
    llm_corpus_learn_guard_enabled: bool = Field(default=True)
    llm_corpus_cleanup_scheduled_enabled: bool = Field(default=True)
    llm_corpus_cleanup_interval_sec: int = Field(default=86400, ge=3600, le=604800)
    llm_corpus_cleanup_message_history_enabled: bool = Field(default=True)
    llm_corpus_cleanup_max_delete_per_round: int = Field(default=20000, ge=100, le=500000)
    llm_tools_blacklist: list[str] = Field(default_factory=list)
    llm_tools_desc_max_len: int = Field(default=120, ge=32, le=512)
    llm_memory_rag_enabled: bool = Field(default=True)
    llm_expression_inject_enabled: bool = Field(default=True)
    llm_expression_learn_enabled: bool = Field(default=True)
    llm_expression_auto_promote_enabled: bool = Field(default=True)
    llm_expression_retrieve_limit: int = Field(default=5, ge=1, le=8)
    llm_vector_retrieve: VectorRetrieveMode = Field(default="hybrid")
    llm_embedding_model: str = Field(default="stub")
    llm_embedding_provider: str = Field(default="")
    llm_embedding_provider_id: str = Field(default="")
    llm_embedding_base_url: str = Field(default="")
    llm_embedding_api_key: str = Field(default="")
    llm_embedding_api_backends: list[dict[str, object]] = Field(default_factory=list)
    llm_memory_rag_top_k: int = Field(default=3, ge=1, le=8)
    llm_memory_rag_min_score: int = Field(default=24, ge=0, le=100)
    llm_memory_max_per_group: int = Field(default=200, ge=1, le=2000)
    llm_memory_content_max_len: int = Field(default=500, ge=64, le=4000)
    llm_memory_auto_episode_enabled: bool = Field(default=False)
    llm_memory_auto_episode_summary_enabled: bool = Field(default=True)
    llm_memory_auto_episode_cooldown_sec: int = Field(default=600, ge=0, le=3600)
    llm_memory_auto_episode_daily_budget: int = Field(default=100, ge=0, le=100000)
    llm_memory_auto_ip_enabled: bool = Field(default=False)
    llm_memory_auto_ip_cooldown_sec: int = Field(default=1800, ge=0, le=86400)
    llm_memory_auto_ip_daily_budget: int = Field(default=100, ge=0, le=100000)
    llm_memory_graph_extract_enabled: bool = Field(default=True)
    llm_memory_graph_extract_on_write: bool = Field(default=False)
    llm_memory_hiergraph_max_layers: int = Field(default=3, ge=1, le=6)
    llm_knowledge_sources_enabled: bool = Field(default=True)
    llm_knowledge_file_ingest_enabled: bool = Field(default=True)
    llm_knowledge_top_k: int = Field(default=3, ge=1, le=8)
    llm_knowledge_min_score: int = Field(default=12, ge=0, le=100)
    llm_knowledge_content_max_len: int = Field(default=400, ge=64, le=2000)
    # 发言感知：别名提及强制进 llm_chat；ambient 为轻量规则插嘴
    llm_speak_perception_enabled: bool = Field(default=True)
    llm_speak_mention_enabled: bool = Field(default=True)
    llm_speak_ambient_enabled: bool = Field(default=True)
    llm_speak_ambient_rate: float = Field(default=0.08, ge=0.0, le=1.0)
    llm_speak_ambient_min_score: int = Field(default=35, ge=0, le=100)
    llm_speak_ambient_cooldown_sec: int = Field(default=120, ge=0, le=3600)
    llm_speak_ambient_budget_limit: int = Field(default=2, ge=0, le=20)
    llm_speak_ambient_budget_window_sec: int = Field(default=900, ge=60, le=86400)
    llm_speak_min_alias_len: int = Field(default=2, ge=1, le=8)
    llm_speak_followup_enabled: bool = Field(default=True)
    llm_speak_followup_window_sec: int = Field(default=45, ge=0, le=600)
    llm_speak_followup_max_total_sec: int = Field(default=180, ge=0, le=3600)
    llm_relationship_notes_enabled: bool = Field(default=True)
    llm_relationship_content_max_len: int = Field(default=200, ge=32, le=2000)
    llm_relationship_half_life_days: float = Field(default=30.0, ge=0.0, le=365.0)
    llm_relationship_min_weight: float = Field(default=0.2, ge=0.0, le=1.0)
    llm_relationship_observe_enabled: bool = Field(default=True)
    llm_relationship_auto_persist_enabled: bool = Field(default=True)
    llm_relationship_affect_delta_max: float = Field(default=0.15, ge=0.0, le=0.5)
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


def _env_json_object(key: str) -> dict[str, object]:
    raw = repo_env_raw_value(key)
    if raw is None:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _env_json_dict_list(key: str) -> list[dict[str, object]]:
    raw = repo_env_raw_value(key)
    if raw is None or not str(raw).strip():
        return []
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


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
        from pallas.product.llm.corpus_contamination import (
            CHAT_HARD_BLOCK_PHRASES,
            CHAT_SOFT_RETRY_PHRASES,
        )

        _cached_llm_config = LlmConfig(
            llm_runtime=resolve_llm_runtime(),
            llm_base_url=resolve_llm_base_url(),
            llm_api_key=resolve_llm_api_key(),
            llm_model=resolve_llm_model(),
            llm_tools_max_rounds=_env_int("LLM_TOOLS_MAX_ROUNDS", 4),
            ai_server_host=host,
            ai_server_port=port,
            llm_chat_enabled=resolve_llm_chat_enabled(),
            chat_tts_enable=resolve_chat_tts_enabled(),
            drunk_tts_min_drunkenness=_env_int("DRUNK_TTS_MIN_DRUNKENNESS", 1),
            drunk_tts_min_chars=_env_int("DRUNK_TTS_MIN_CHARS", 6),
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
            llm_tools_soft_recall_enabled=_env_bool("LLM_TOOLS_SOFT_RECALL_ENABLED", True),
            llm_tools_soft_recall_min_score=_env_int("LLM_TOOLS_SOFT_RECALL_MIN_SCORE", 6),
            llm_tools_soft_recall_max_candidates=_env_int("LLM_TOOLS_SOFT_RECALL_MAX_CANDIDATES", 3),
            llm_chat_cooldown_sec=_env_int("LLM_CHAT_COOLDOWN_SEC", 3),
            llm_chat_max_concurrency=_env_int("LLM_CHAT_MAX_CONCURRENCY", 2),
            llm_shared_max_concurrency=_env_int("LLM_SHARED_MAX_CONCURRENCY", 4),
            llm_chat_queue_enabled=_env_bool("LLM_CHAT_QUEUE_ENABLED", True),
            llm_chat_queue_max=_env_int("LLM_CHAT_QUEUE_MAX", 8),
            llm_chat_queue_wait_sec=_env_float("LLM_CHAT_QUEUE_WAIT_SEC", 20.0),
            llm_chat_char_budget=_env_int("LLM_CHAT_CHAR_BUDGET", 12000),
            llm_chat_disabled_group_ids=_env_group_id_list("LLM_CHAT_DISABLED_GROUP_IDS"),
            llm_repeater_feedback_enabled=_env_bool("LLM_REPEATER_FEEDBACK_ENABLED", True),
            llm_repeater_bias_enabled=_env_bool("LLM_REPEATER_BIAS_ENABLED", True),
            llm_repeater_writeback_enabled=_env_bool("LLM_REPEATER_WRITEBACK_ENABLED", True),
            conversation_feature_level=resolve_conversation_feature_level_raw(),
            llm_reply_gate_enabled=_env_bool("LLM_REPLY_GATE_ENABLED", True),
            llm_current_turn_decision_enabled=_env_bool("LLM_CURRENT_TURN_DECISION_ENABLED", False),
            llm_current_turn_decision_model=_env_str("LLM_CURRENT_TURN_DECISION_MODEL"),
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
            llm_persona_output_firewall=_env_json_object("LLM_PERSONA_OUTPUT_FIREWALL"),
            llm_reply_postprocess_enabled=_env_bool("LLM_REPLY_POSTPROCESS_ENABLED", False),
            llm_reply_typo_enabled=_env_bool("LLM_REPLY_TYPO_ENABLED", False),
            llm_reply_typo_rate=_env_float("LLM_REPLY_TYPO_RATE", 0.01),
            llm_reply_trim_terminal_period_enabled=_env_bool("LLM_REPLY_TRIM_TERMINAL_PERIOD_ENABLED", True),
            llm_reply_trim_terminal_period_rate=_env_float("LLM_REPLY_TRIM_TERMINAL_PERIOD_RATE", 0.9),
            llm_reply_mention_cooldown_sec=_env_int("LLM_REPLY_MENTION_COOLDOWN_SEC", 900),
            llm_sticker_fit_enabled=_env_bool("LLM_STICKER_FIT_ENABLED", False),
            llm_chat_sticker_enabled=_env_bool("LLM_CHAT_STICKER_ENABLED", True),
            llm_chat_sticker_cooldown_sec=_env_int("LLM_CHAT_STICKER_COOLDOWN_SEC", 90),
            llm_chat_sticker_max_per_hour=_env_int("LLM_CHAT_STICKER_MAX_PER_HOUR", 8),
            llm_sticker_vision_enabled=_env_bool("LLM_STICKER_VISION_ENABLED", False),
            llm_sticker_vision_candidate_count=_env_int("LLM_STICKER_VISION_CANDIDATE_COUNT", 4),
            llm_sticker_vision_timeout_sec=_env_float("LLM_STICKER_VISION_TIMEOUT_SEC", 15.0),
            llm_sticker_vision_max_per_hour=_env_int("LLM_STICKER_VISION_MAX_PER_HOUR", 12),
            llm_sticker_label_backfill_enabled=_env_bool("LLM_STICKER_LABEL_BACKFILL_ENABLED", True),
            llm_sticker_label_backfill_daily_limit=_env_int("LLM_STICKER_LABEL_BACKFILL_DAILY_LIMIT", 200),
            llm_sticker_label_realtime_daily_limit=_env_int("LLM_STICKER_LABEL_REALTIME_DAILY_LIMIT", 300),
            llm_reply_effect_eval_enabled=_env_bool("LLM_REPLY_EFFECT_EVAL_ENABLED", False),
            llm_reply_style_variants=_env_json_object("LLM_REPLY_STYLE_VARIANTS"),
            llm_corpus_learn_guard_enabled=_env_bool("LLM_CORPUS_LEARN_GUARD_ENABLED", True),
            llm_corpus_cleanup_scheduled_enabled=_env_bool("LLM_CORPUS_CLEANUP_SCHEDULED", True),
            llm_corpus_cleanup_interval_sec=_env_int("LLM_CORPUS_CLEANUP_INTERVAL_SEC", 86400),
            llm_corpus_cleanup_message_history_enabled=_env_bool(
                "LLM_CORPUS_CLEANUP_MESSAGE_HISTORY",
                True,
            ),
            llm_corpus_cleanup_max_delete_per_round=_env_int(
                "LLM_CORPUS_CLEANUP_MAX_DELETE_PER_ROUND",
                20000,
            ),
            llm_tools_blacklist=_env_str_list("LLM_TOOLS_BLACKLIST"),
            llm_tools_desc_max_len=_env_int("LLM_TOOLS_DESC_MAX_LEN", 120),
            llm_memory_rag_enabled=_env_bool("LLM_MEMORY_RAG_ENABLED", True),
            llm_expression_inject_enabled=_env_bool("LLM_EXPRESSION_INJECT_ENABLED", True),
            llm_expression_learn_enabled=_env_bool("LLM_EXPRESSION_LEARN_ENABLED", True),
            llm_expression_auto_promote_enabled=_env_bool("LLM_EXPRESSION_AUTO_PROMOTE_ENABLED", True),
            llm_expression_retrieve_limit=min(8, max(1, _env_int("LLM_EXPRESSION_RETRIEVE_LIMIT", 5))),
            llm_vector_retrieve=resolve_llm_vector_retrieve(),
            llm_embedding_model=resolve_llm_embedding_model(),
            llm_embedding_provider=resolve_llm_embedding_provider(),
            llm_embedding_provider_id=str(repo_env_raw_value("LLM_EMBEDDING_PROVIDER_ID") or "").strip(),
            llm_embedding_base_url=str(repo_env_raw_value("LLM_EMBEDDING_BASE_URL") or "").strip(),
            llm_embedding_api_key=str(repo_env_raw_value("LLM_EMBEDDING_API_KEY") or "").strip(),
            llm_embedding_api_backends=_env_json_dict_list("LLM_EMBEDDING_API_BACKENDS"),
            llm_memory_rag_top_k=_env_int("LLM_MEMORY_RAG_TOP_K", 3),
            llm_memory_rag_min_score=_env_int("LLM_MEMORY_RAG_MIN_SCORE", 24),
            llm_memory_max_per_group=_env_int("LLM_MEMORY_MAX_PER_GROUP", 200),
            llm_memory_content_max_len=_env_int("LLM_MEMORY_CONTENT_MAX_LEN", 500),
            llm_memory_auto_episode_enabled=_env_bool("LLM_MEMORY_AUTO_EPISODE_ENABLED", False),
            llm_memory_auto_episode_summary_enabled=_env_bool("LLM_MEMORY_AUTO_EPISODE_SUMMARY_ENABLED", True),
            llm_memory_auto_episode_cooldown_sec=_env_int("LLM_MEMORY_AUTO_EPISODE_COOLDOWN_SEC", 600),
            llm_memory_auto_episode_daily_budget=_env_int("LLM_MEMORY_AUTO_EPISODE_DAILY_BUDGET", 100),
            llm_memory_auto_ip_enabled=_env_bool("LLM_MEMORY_AUTO_IP_ENABLED", False),
            llm_memory_auto_ip_cooldown_sec=_env_int("LLM_MEMORY_AUTO_IP_COOLDOWN_SEC", 1800),
            llm_memory_auto_ip_daily_budget=_env_int("LLM_MEMORY_AUTO_IP_DAILY_BUDGET", 100),
            llm_memory_graph_extract_enabled=_env_bool("LLM_MEMORY_GRAPH_EXTRACT_ENABLED", True),
            llm_memory_graph_extract_on_write=_env_bool("LLM_MEMORY_GRAPH_EXTRACT_ON_WRITE", False),
            llm_memory_hiergraph_max_layers=_env_int("LLM_MEMORY_HIERGRAPH_MAX_LAYERS", 3),
            llm_knowledge_sources_enabled=_env_bool("LLM_KNOWLEDGE_SOURCES_ENABLED", True),
            llm_knowledge_file_ingest_enabled=_env_bool("LLM_KNOWLEDGE_FILE_INGEST_ENABLED", True),
            llm_knowledge_top_k=_env_int("LLM_KNOWLEDGE_TOP_K", 3),
            llm_knowledge_min_score=_env_int("LLM_KNOWLEDGE_MIN_SCORE", 12),
            llm_knowledge_content_max_len=_env_int("LLM_KNOWLEDGE_CONTENT_MAX_LEN", 400),
            llm_speak_perception_enabled=_env_bool("LLM_SPEAK_PERCEPTION_ENABLED", True),
            llm_speak_mention_enabled=_env_bool("LLM_SPEAK_MENTION_ENABLED", True),
            llm_speak_ambient_enabled=_env_bool("LLM_SPEAK_AMBIENT_ENABLED", True),
            llm_speak_ambient_rate=_env_float("LLM_SPEAK_AMBIENT_RATE", 0.08),
            llm_speak_ambient_min_score=_env_int("LLM_SPEAK_AMBIENT_MIN_SCORE", 35),
            llm_speak_ambient_cooldown_sec=_env_int("LLM_SPEAK_AMBIENT_COOLDOWN_SEC", 120),
            llm_speak_ambient_budget_limit=_env_int("LLM_SPEAK_AMBIENT_BUDGET_LIMIT", 2),
            llm_speak_ambient_budget_window_sec=_env_int("LLM_SPEAK_AMBIENT_BUDGET_WINDOW_SEC", 900),
            llm_speak_min_alias_len=_env_int("LLM_SPEAK_MIN_ALIAS_LEN", 2),
            llm_speak_followup_enabled=_env_bool("LLM_SPEAK_FOLLOWUP_ENABLED", True),
            llm_speak_followup_window_sec=_env_int("LLM_SPEAK_FOLLOWUP_WINDOW_SEC", 45),
            llm_speak_followup_max_total_sec=_env_int("LLM_SPEAK_FOLLOWUP_MAX_TOTAL_SEC", 180),
            llm_relationship_notes_enabled=_env_bool("LLM_RELATIONSHIP_NOTES_ENABLED", True),
            llm_relationship_content_max_len=_env_int("LLM_RELATIONSHIP_CONTENT_MAX_LEN", 200),
            llm_relationship_half_life_days=_env_float("LLM_RELATIONSHIP_HALF_LIFE_DAYS", 30.0),
            llm_relationship_min_weight=_env_float("LLM_RELATIONSHIP_MIN_WEIGHT", 0.2),
            llm_relationship_observe_enabled=_env_bool("LLM_RELATIONSHIP_OBSERVE_ENABLED", True),
            llm_relationship_auto_persist_enabled=_env_bool("LLM_RELATIONSHIP_AUTO_PERSIST_ENABLED", True),
            llm_relationship_affect_delta_max=_env_float("LLM_RELATIONSHIP_AFFECT_DELTA_MAX", 0.15),
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
        from pallas.product.llm.knowledge.embedding_provider import clear_embedding_provider_cache

        clear_embedding_provider_cache()
    except Exception:
        pass
    try:
        from pallas.product.llm.feedback_embedding_cache import (
            invalidate_feedback_embedding_caches,
            schedule_feedback_trigger_backfill,
        )

        invalidate_feedback_embedding_caches()
        schedule_feedback_trigger_backfill()
    except Exception:
        pass
    try:
        from .governance import clear_llm_chat_governance_state

        clear_llm_chat_governance_state()
    except Exception:
        pass


def llm_server_base_url(cfg: LlmConfig | None = None) -> str:
    c = cfg or get_llm_config()
    return f"http://{c.ai_server_host}:{c.ai_server_port}"


def llm_provider_configured(cfg: LlmConfig | None = None) -> bool:
    from pallas.product.llm.providers_store import bot_providers_configured

    if bot_providers_configured(task="llm_chat"):
        return True
    c = cfg or get_llm_config()
    return bool(str(c.llm_base_url or "").strip() and str(c.llm_model or "").strip())
