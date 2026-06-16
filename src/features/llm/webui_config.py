"""WebUI 通用配置：LLM 全局开关与 AI 服务地址。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.console.webui.field_help import field_help
from src.features.llm.config import get_llm_config

RepeaterMode = Literal["off", "fallback", "polish", "both"]


class LlmWebuiConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ai_server_host: str = Field(
        default="127.0.0.1",
        description=field_help("智能对话服务所在主机的地址", "本机部署填 127.0.0.1；远程填 IP 或域名"),
    )
    ai_server_port: int = Field(
        default=9099,
        ge=1,
        le=65535,
        description=field_help("智能对话服务监听的端口", "与 Pallas-Bot-AI 的 .env 中端口一致"),
    )
    llm_chat_enabled: bool = Field(
        default=False,
        description=field_help(
            "是否启用智能对话",
            "开启后可用「随时闲聊」等口令，并影响接话时的 AI 能力",
        ),
    )
    llm_repeater_mode: RepeaterMode = Field(
        default="both",
        description=field_help(
            "接话时如何使用智能对话",
            "关闭 / 语料没有时现编 / 命中语料后润色 / 两者都用",
            "选项：off、fallback、polish、both",
        ),
    )
    llm_governance_enabled: bool = Field(
        default=True,
        description=field_help(
            "是否限制闲聊的频率与单次字数",
            "群很活跃时建议开启，避免刷屏",
        ),
    )
    llm_session_enabled: bool = Field(
        default=True,
        description=field_help(
            "是否记住多轮对话上下文",
            "开启后「随时闲聊」可连续聊；关闭则每句独立",
        ),
    )
    llm_tools_enabled: bool = Field(
        default=True,
        description=field_help(
            "是否允许智能对话调用方舟等资料工具",
            "需同时开启智能对话总闸与 AI 仓 LLM_TOOLS_ENABLED",
        ),
    )


def get_llm_webui_config() -> LlmWebuiConfig:
    cfg = get_llm_config()
    mode = cfg.llm_repeater_mode if cfg.llm_repeater_mode in ("off", "fallback", "polish", "both") else "both"
    return LlmWebuiConfig(
        ai_server_host=cfg.ai_server_host,
        ai_server_port=cfg.ai_server_port,
        llm_chat_enabled=cfg.llm_chat_enabled,
        llm_repeater_mode=mode,  # type: ignore[arg-type]
        llm_governance_enabled=cfg.llm_governance_enabled,
        llm_session_enabled=cfg.llm_session_enabled,
        llm_tools_enabled=cfg.llm_tools_enabled,
    )
