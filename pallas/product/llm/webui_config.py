"""WebUI 通用配置：LLM 全局开关与 AI 服务地址。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from pallas.console.webui.field_help import field_help
from pallas.product.llm.config import get_llm_config

VectorRetrieveMode = Literal["keyword", "embedding", "hybrid", "vector"]
RepeaterMode = Literal["off", "select", "select_polish_lite", "select_fallback", "fallback"]

_LEGACY_REPEATER_MODE_TO_WEBUI: dict[str, RepeaterMode] = {
    "polish": "select_polish_lite",
    "both": "select_fallback",
}


def normalize_repeater_mode_for_webui(mode: str) -> RepeaterMode:
    raw = str(mode or "").strip().lower()
    if raw in _LEGACY_REPEATER_MODE_TO_WEBUI:
        return _LEGACY_REPEATER_MODE_TO_WEBUI[raw]
    if raw in ("off", "select", "select_polish_lite", "select_fallback", "fallback"):
        return raw  # type: ignore[return-value]
    return "select"


ConversationFeatureLevel = Literal["", "legacy_repeater", "repeater_plus_decision", "full_conversation_kernel"]


def default_output_filter_chat_hard_phrases() -> list[str]:
    from pallas.product.llm.output_filter import CHAT_HARD_BLOCK_PHRASES

    return list(CHAT_HARD_BLOCK_PHRASES)


def default_output_filter_chat_soft_phrases() -> list[str]:
    from pallas.product.llm.output_filter import CHAT_SOFT_RETRY_PHRASES

    return list(CHAT_SOFT_RETRY_PHRASES)


def default_output_filter_polish_lite_hard_phrases() -> list[str]:
    from pallas.product.llm.output_filter import POLISH_LITE_HARD_BLOCK_PHRASES

    return list(POLISH_LITE_HARD_BLOCK_PHRASES)


def default_output_filter_polish_lite_soft_phrases() -> list[str]:
    from pallas.product.llm.output_filter import POLISH_LITE_SOFT_RETRY_PHRASES

    return list(POLISH_LITE_SOFT_RETRY_PHRASES)


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
        default="select",
        description=field_help(
            "接话时如何使用智能对话",
            "推荐「命中语料时 AI 选句」；需要时可开启语料缺失现编，或少数回复做轻润色",
            (
                "off=只用语料；select=命中语料时 AI 选句；"
                "select_polish_lite=以选句为主，约一成回复会轻润色口气；"
                "select_fallback=选句且语料缺失时现编；fallback=仅语料缺失时现编"
            ),
        ),
    )
    llm_polish_lite_sample_rate: float = Field(
        default=0.12,
        ge=0.0,
        le=1.0,
        description=field_help(
            "「选句为主，少数回复轻润色」模式下走轻润色的比例",
            "0.12 表示约 12% 命中语料会轻润色口气，其余仍走选句",
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
    llm_chat_max_concurrency: int = Field(
        default=2,
        ge=1,
        le=64,
        description=field_help(
            "同时向 AI 提交的闲聊请求上限",
            "每个分片 worker 进程独立计数；@ 闲聊与接话分开限流",
        ),
    )
    llm_repeater_group_cooldown_sec: int = Field(
        default=60,
        ge=0,
        le=3600,
        description=field_help(
            "同一群两次接话 AI 请求的最短间隔（秒）",
            "0 表示不限制群冷却",
        ),
    )
    llm_repeater_max_inflight: int = Field(
        default=1,
        ge=1,
        le=32,
        description=field_help(
            "每个 worker 同时进行的接话 AI 请求数",
            "与闲聊并发分开计算",
        ),
    )
    llm_repeater_global_rpm: int = Field(
        default=10,
        ge=1,
        le=600,
        description=field_help(
            "全实例每分钟接话 AI 请求上限",
            "有 Redis 时全局限流；否则按 worker 数分摊",
        ),
    )
    llm_repeater_feedback_enabled: bool = Field(
        default=False,
        description=field_help(
            "是否收集闲聊成功回复，作为复读软反馈",
            "只在回复真正发出后记录；默认只收集，不改复读行为",
        ),
    )
    llm_repeater_bias_enabled: bool = Field(
        default=False,
        description=field_help(
            "是否让复读轻微偏向已被闲聊验证过的短回复",
            "保守弱偏置；样本不足时不会生效",
        ),
    )
    llm_repeater_writeback_enabled: bool = Field(
        default=False,
        description=field_help(
            "是否允许将软反馈回写到复读学习语料",
            "默认关闭；后续确认策略后再开启",
        ),
    )
    conversation_feature_level: ConversationFeatureLevel = Field(
        default="",
        description=field_help(
            "对话内核能力档位",
            "留空则按现有开关自动推断；legacy=仅语料规则，plus=统一决策，full=决策+生成+反馈全链路",
        ),
    )
    llm_reply_gate_enabled: bool = Field(
        default=True,
        description=field_help(
            "是否过滤纯表情等不值得回复的 @",
            "开启后表情包 @ 不会提交 AI",
        ),
    )
    llm_chat_queue_merge: bool = Field(
        default=True,
        description=field_help(
            "冷却期间是否合并多条 @",
            "开启后 CD 内连发只保留最后一次 completion",
        ),
    )
    llm_output_filter_enabled: bool = Field(
        default=True,
        description=field_help(
            "是否启用 AI 回复输出后过滤",
            "拦截客服腔、邀约尾缀等；接话任务优先回落语料原文",
        ),
    )
    llm_output_filter_chat_hard_phrases: list[str] = Field(
        default_factory=default_output_filter_chat_hard_phrases,
        description=field_help(
            "闲聊/接话硬拦截词表",
            "JSON 字符串数组；命中后接话回落语料，闲聊静默不发",
        ),
    )
    llm_output_filter_chat_soft_phrases: list[str] = Field(
        default_factory=default_output_filter_chat_soft_phrases,
        description=field_help(
            "闲聊/接话软拦截词表",
            "JSON 字符串数组；与硬拦截同样处理，便于分批下线",
        ),
    )
    llm_output_filter_polish_lite_hard_phrases: list[str] = Field(
        default_factory=default_output_filter_polish_lite_hard_phrases,
        description=field_help(
            "接话轻润色额外硬拦截词",
            "与上方闲聊硬拦截合并后用于 repeater_polish_lite",
        ),
    )
    llm_output_filter_polish_lite_soft_phrases: list[str] = Field(
        default_factory=default_output_filter_polish_lite_soft_phrases,
        description=field_help(
            "接话轻润色额外软拦截词",
            "与上方闲聊软拦截合并后用于 repeater_polish_lite",
        ),
    )
    llm_memory_rag_enabled: bool = Field(
        default=True,
        description=field_help(
            "是否启用群记忆检索",
            "开启后可将「记住：…」写入记忆，并按相关度注入对话",
        ),
    )
    llm_vector_retrieve: VectorRetrieveMode = Field(
        default="hybrid",
        description=field_help(
            "群记忆与知识源的检索方式",
            "hybrid=关键词+向量（默认，需 AI 仓 embeddings）；keyword=仅关键词；embedding=纯向量",
        ),
    )
    llm_embedding_model: str = Field(
        default="stub",
        description=field_help(
            "向量检索使用的 embedding 模型名",
            "与 Pallas-Bot-AI embeddings 接口一致；本地联调可填 stub",
        ),
    )
    llm_relationship_notes_enabled: bool = Field(
        default=True,
        description=field_help(
            "是否启用关系备注层",
            "开启后可对 @某人 教导稳定关系（如「记住关系：xx是群主」），随时间衰减",
        ),
    )


def get_llm_webui_config() -> LlmWebuiConfig:
    cfg = get_llm_config()
    mode = normalize_repeater_mode_for_webui(cfg.llm_repeater_mode)
    return LlmWebuiConfig(
        ai_server_host=cfg.ai_server_host,
        ai_server_port=cfg.ai_server_port,
        llm_chat_enabled=cfg.llm_chat_enabled,
        llm_repeater_mode=mode,  # type: ignore[arg-type]
        llm_polish_lite_sample_rate=cfg.llm_polish_lite_sample_rate,
        llm_governance_enabled=cfg.llm_governance_enabled,
        llm_session_enabled=cfg.llm_session_enabled,
        llm_tools_enabled=cfg.llm_tools_enabled,
        llm_chat_max_concurrency=cfg.llm_chat_max_concurrency,
        llm_repeater_group_cooldown_sec=cfg.llm_repeater_group_cooldown_sec,
        llm_repeater_max_inflight=cfg.llm_repeater_max_inflight,
        llm_repeater_global_rpm=cfg.llm_repeater_global_rpm,
        llm_repeater_feedback_enabled=cfg.llm_repeater_feedback_enabled,
        llm_repeater_bias_enabled=cfg.llm_repeater_bias_enabled,
        llm_repeater_writeback_enabled=cfg.llm_repeater_writeback_enabled,
        conversation_feature_level=cfg.conversation_feature_level or "",  # type: ignore[arg-type]
        llm_reply_gate_enabled=cfg.llm_reply_gate_enabled,
        llm_chat_queue_merge=cfg.llm_chat_queue_merge,
        llm_output_filter_enabled=cfg.llm_output_filter_enabled,
        llm_output_filter_chat_hard_phrases=cfg.llm_output_filter_chat_hard_phrases,
        llm_output_filter_chat_soft_phrases=cfg.llm_output_filter_chat_soft_phrases,
        llm_output_filter_polish_lite_hard_phrases=cfg.llm_output_filter_polish_lite_hard_phrases,
        llm_output_filter_polish_lite_soft_phrases=cfg.llm_output_filter_polish_lite_soft_phrases,
        llm_memory_rag_enabled=cfg.llm_memory_rag_enabled,
        llm_vector_retrieve=cfg.llm_vector_retrieve,
        llm_embedding_model=cfg.llm_embedding_model,
        llm_relationship_notes_enabled=cfg.llm_relationship_notes_enabled,
    )
