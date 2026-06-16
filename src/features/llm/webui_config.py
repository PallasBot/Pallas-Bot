"""WebUI 通用配置：LLM 全局开关与 AI 服务地址。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.features.llm.config import get_llm_config

RepeaterMode = Literal["off", "fallback", "polish", "both"]


class LlmWebuiConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ai_server_host: str = Field(default="127.0.0.1", description="Pallas-Bot-AI 主机")
    ai_server_port: int = Field(default=9099, ge=1, le=65535, description="Pallas-Bot-AI 端口")
    llm_chat_enabled: bool = Field(default=False, description="LLM 总闸（闲聊与接话 LLM 共用）")
    llm_repeater_mode: RepeaterMode = Field(
        default="off",
        description="repeater 接话 LLM：off / fallback / polish / both",
    )
    llm_governance_enabled: bool = Field(default=False, description="闲聊 CD / 并发 / 字符预算")
    llm_session_enabled: bool = Field(default=False, description="多轮会话存储")


def get_llm_webui_config() -> LlmWebuiConfig:
    cfg = get_llm_config()
    mode = cfg.llm_repeater_mode if cfg.llm_repeater_mode in ("off", "fallback", "polish", "both") else "off"
    return LlmWebuiConfig(
        ai_server_host=cfg.ai_server_host,
        ai_server_port=cfg.ai_server_port,
        llm_chat_enabled=cfg.llm_chat_enabled,
        llm_repeater_mode=mode,  # type: ignore[arg-type]
        llm_governance_enabled=cfg.llm_governance_enabled,
        llm_session_enabled=cfg.llm_session_enabled,
    )
