"""会话 / 记忆配置子集 DTO，供独立控制台 API 读写（仍落盘到 llm 段）。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from pallas.product.llm.webui_config import LlmWebuiConfig, VectorRetrieveMode, get_llm_webui_config

SESSION_FIELD_NAMES = (
    "llm_session_enabled",
    "llm_session_user_window",
    "llm_session_group_window",
    "llm_session_group_ambient_enabled",
    "llm_session_user_ttl_sec",
    "llm_session_private_ttl_sec",
    "llm_session_max_content_len",
    "llm_session_strip_vision_enabled",
    "llm_session_summary_enabled",
    "llm_session_summary_threshold",
    "llm_session_summary_keep_messages",
)

MEMORY_FIELD_NAMES = (
    "llm_memory_rag_enabled",
    "llm_vector_retrieve",
    "llm_embedding_model",
    "llm_embedding_provider",
    "llm_memory_rag_top_k",
    "llm_memory_max_per_group",
    "llm_memory_content_max_len",
    "llm_memory_auto_episode_enabled",
    "llm_memory_auto_episode_cooldown_sec",
    "llm_memory_graph_extract_enabled",
    "llm_memory_graph_extract_on_write",
    "llm_memory_hiergraph_max_layers",
    "llm_relationship_notes_enabled",
)


class LlmSessionOpsConfig(BaseModel):
    llm_session_enabled: bool = True
    llm_session_user_window: int = Field(default=18, ge=1, le=200)
    llm_session_group_window: int = Field(default=8, ge=0, le=100)
    llm_session_group_ambient_enabled: bool = True
    llm_session_user_ttl_sec: int = Field(default=0, ge=0, le=2592000)
    llm_session_private_ttl_sec: int = Field(default=259200, ge=0, le=2592000)
    llm_session_max_content_len: int = Field(default=4000, ge=64, le=16000)
    llm_session_strip_vision_enabled: bool = True
    llm_session_summary_enabled: bool = True
    llm_session_summary_threshold: int = Field(default=40, ge=8, le=200)
    llm_session_summary_keep_messages: int = Field(default=16, ge=4, le=120)


class LlmMemoryOpsConfig(BaseModel):
    llm_memory_rag_enabled: bool = True
    llm_vector_retrieve: VectorRetrieveMode = "hybrid"
    llm_embedding_model: str = "stub"
    llm_embedding_provider: str = ""
    llm_memory_rag_top_k: int = Field(default=3, ge=1, le=8)
    llm_memory_max_per_group: int = Field(default=200, ge=1, le=2000)
    llm_memory_content_max_len: int = Field(default=500, ge=64, le=4000)
    llm_memory_auto_episode_enabled: bool = True
    llm_memory_auto_episode_cooldown_sec: int = Field(default=120, ge=0, le=3600)
    llm_memory_graph_extract_enabled: bool = True
    llm_memory_graph_extract_on_write: bool = False
    llm_memory_hiergraph_max_layers: int = Field(default=3, ge=1, le=6)
    llm_relationship_notes_enabled: bool = True


def get_llm_session_ops_config(cfg: LlmWebuiConfig | None = None) -> LlmSessionOpsConfig:
    source = cfg or get_llm_webui_config()
    data = {name: getattr(source, name) for name in SESSION_FIELD_NAMES}
    return LlmSessionOpsConfig.model_validate(data)


def get_llm_memory_ops_config(cfg: LlmWebuiConfig | None = None) -> LlmMemoryOpsConfig:
    source = cfg or get_llm_webui_config()
    data = {name: getattr(source, name) for name in MEMORY_FIELD_NAMES}
    return LlmMemoryOpsConfig.model_validate(data)


def session_ops_patch_dict(body: dict[str, Any]) -> dict[str, Any]:
    parsed = LlmSessionOpsConfig.model_validate({
        **get_llm_session_ops_config().model_dump(),
        **{k: v for k, v in body.items() if k in SESSION_FIELD_NAMES},
    })
    return parsed.model_dump()


def memory_ops_patch_dict(body: dict[str, Any]) -> dict[str, Any]:
    parsed = LlmMemoryOpsConfig.model_validate({
        **get_llm_memory_ops_config().model_dump(),
        **{k: v for k, v in body.items() if k in MEMORY_FIELD_NAMES},
    })
    return parsed.model_dump()
