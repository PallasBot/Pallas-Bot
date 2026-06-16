"""WebUI 通用配置：LLM 全局开关与 AI 服务地址。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from src.features.llm.config import get_llm_config


class LlmWebuiConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ai_server_host: str = Field(default="127.0.0.1", description="Pallas-Bot-AI 主机")
    ai_server_port: int = Field(default=9099, ge=1, le=65535, description="Pallas-Bot-AI 端口")
    llm_chat_enabled: bool = Field(default=False, description="LLM 总闸（闲聊与接话 LLM 共用）")
    llm_fallback_enabled: bool = Field(default=False, description="repeater 语料 miss 时 LLM 生成")
    llm_polish_enabled: bool = Field(default=False, description="repeater 命中语料时 LLM 轻改写")
    llm_governance_enabled: bool = Field(default=False, description="闲聊 CD / 并发 / 字符预算")
    llm_session_enabled: bool = Field(default=False, description="多轮会话存储")


def get_llm_webui_config() -> LlmWebuiConfig:
    cfg = get_llm_config()
    return LlmWebuiConfig(
        ai_server_host=cfg.ai_server_host,
        ai_server_port=cfg.ai_server_port,
        llm_chat_enabled=cfg.llm_chat_enabled,
        llm_fallback_enabled=cfg.llm_fallback_enabled,
        llm_polish_enabled=cfg.llm_polish_enabled,
        llm_governance_enabled=cfg.llm_governance_enabled,
        llm_session_enabled=cfg.llm_session_enabled,
    )
