from __future__ import annotations

import json
from threading import Lock

from pydantic import BaseModel, ConfigDict, Field

from src.foundation.config.repo_settings import repo_env_raw_value

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
        from src.plugins.chat.config import get_chat_config

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
    if raw in ("off", "fallback", "polish", "both"):
        return raw
    fallback = _env_bool("LLM_FALLBACK_ENABLED", False)
    polish = _env_bool("LLM_POLISH_ENABLED", False)
    if fallback and polish:
        return "both"
    if fallback:
        return "fallback"
    if polish:
        return "polish"
    return "off"


def resolve_llm_repeater_flags() -> tuple[bool, bool]:
    mode = resolve_llm_repeater_mode()
    if mode == "off":
        return False, False
    if mode == "fallback":
        return True, False
    if mode == "polish":
        return False, True
    return True, True


class LlmConfig(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    ai_server_host: str = Field(default="127.0.0.1")
    ai_server_port: int = Field(default=9099, ge=1, le=65535)
    llm_chat_enabled: bool = Field(default=False)
    llm_repeater_mode: str = Field(default="off")
    llm_fallback_enabled: bool = Field(default=False)
    llm_polish_enabled: bool = Field(default=False)
    use_unified_chat_api: bool = Field(default=True)
    legacy_chat_endpoint: str = Field(default="/api/llm/chat")
    legacy_del_session_endpoint: str = Field(default="/api/llm/del_session")
    unified_chat_endpoint: str = Field(default="/api/v1/chat/completions")
    unified_del_session_endpoint: str = Field(default="/api/v1/chat/completions/session")
    user_message_max_len: int = Field(default=4000, ge=64, le=16000)
    chat_timeout_sec: float = Field(default=30.0, ge=1.0, le=300.0)
    llm_session_enabled: bool = Field(default=False)
    llm_session_user_window: int = Field(default=18, ge=1, le=200)
    llm_session_group_window: int = Field(default=8, ge=0, le=100)
    llm_session_group_ambient_enabled: bool = Field(default=True)
    llm_session_user_ttl_sec: int = Field(default=86400, ge=0, le=2592000)
    llm_session_private_ttl_sec: int = Field(default=259200, ge=0, le=2592000)
    llm_session_max_content_len: int = Field(default=4000, ge=64, le=16000)
    llm_governance_enabled: bool = Field(default=False)
    llm_chat_cooldown_sec: int = Field(default=3, ge=0, le=3600)
    llm_chat_max_concurrency: int = Field(default=4, ge=1, le=64)
    llm_chat_char_budget: int = Field(default=12000, ge=0, le=200000)
    llm_chat_disabled_group_ids: list[int] = Field(default_factory=list)


def get_llm_config() -> LlmConfig:
    global _cached_llm_config
    with _config_lock:
        if _cached_llm_config is not None:
            return _cached_llm_config
        host = _env_str("LLM_AI_SERVER_HOST") or _env_str("AI_SERVER_HOST") or "127.0.0.1"
        port = _env_int("LLM_AI_SERVER_PORT", _env_int("AI_SERVER_PORT", 9099))
        repeater_mode = resolve_llm_repeater_mode()
        fallback_enabled, polish_enabled = resolve_llm_repeater_flags()
        _cached_llm_config = LlmConfig(
            ai_server_host=host,
            ai_server_port=port,
            llm_chat_enabled=resolve_llm_chat_enabled(),
            llm_repeater_mode=repeater_mode,
            llm_fallback_enabled=fallback_enabled,
            llm_polish_enabled=polish_enabled,
            use_unified_chat_api=_env_bool("LLM_USE_UNIFIED_CHAT_API", True),
            legacy_chat_endpoint=_env_str("LLM_LEGACY_CHAT_ENDPOINT", "/api/llm/chat"),
            legacy_del_session_endpoint=_env_str("LLM_LEGACY_DEL_SESSION_ENDPOINT", "/api/llm/del_session"),
            unified_chat_endpoint=_env_str("LLM_UNIFIED_CHAT_ENDPOINT", "/api/v1/chat/completions"),
            unified_del_session_endpoint=_env_str(
                "LLM_UNIFIED_DEL_SESSION_ENDPOINT",
                "/api/v1/chat/completions/session",
            ),
            user_message_max_len=_env_int("LLM_USER_MESSAGE_MAX_LEN", 4000),
            chat_timeout_sec=_env_float("LLM_CHAT_TIMEOUT_SEC", 30.0),
            llm_session_enabled=_env_bool("LLM_SESSION_ENABLED", False),
            llm_session_user_window=_env_int("LLM_SESSION_USER_WINDOW", 18),
            llm_session_group_window=_env_int("LLM_SESSION_GROUP_WINDOW", 8),
            llm_session_group_ambient_enabled=_env_bool("LLM_SESSION_GROUP_AMBIENT_ENABLED", True),
            llm_session_user_ttl_sec=_env_int("LLM_SESSION_USER_TTL_SEC", 86400),
            llm_session_private_ttl_sec=_env_int("LLM_SESSION_PRIVATE_TTL_SEC", 259200),
            llm_session_max_content_len=_env_int("LLM_SESSION_MAX_CONTENT_LEN", 4000),
            llm_governance_enabled=_env_bool("LLM_GOVERNANCE_ENABLED", False),
            llm_chat_cooldown_sec=_env_int("LLM_CHAT_COOLDOWN_SEC", 3),
            llm_chat_max_concurrency=_env_int("LLM_CHAT_MAX_CONCURRENCY", 4),
            llm_chat_char_budget=_env_int("LLM_CHAT_CHAR_BUDGET", 12000),
            llm_chat_disabled_group_ids=_env_group_id_list("LLM_CHAT_DISABLED_GROUP_IDS"),
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


def llm_server_base_url(cfg: LlmConfig | None = None) -> str:
    c = cfg or get_llm_config()
    return f"http://{c.ai_server_host}:{c.ai_server_port}"
