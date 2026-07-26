"""WebUI 通用配置：LLM 全局开关、Bot 内核对话策略与媒体服务地址。"""

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
        description=field_help(
            "AI Runtime（媒体服务）所在主机",
            "唱歌/TTS 等媒体任务用；默认 LLM 聊天走 Bot 内核 Provider，不依赖此项",
        ),
    )
    ai_server_port: int = Field(
        default=9099,
        ge=1,
        le=65535,
        description=field_help(
            "AI Runtime 监听端口",
            "与 Pallas-Bot-AI 的端口一致；推荐在「媒体服务」页修改并同步",
        ),
    )
    llm_chat_enabled: bool = Field(
        default=False,
        description=field_help(
            "是否启用智能对话",
            "开启后可用「智能对话」等口令，并影响接话时的模型能力（走 Bot 内核 Provider）",
        ),
    )
    chat_enable: bool = Field(
        default=False,
        description=field_help(
            "是否启用遗留酒后 RWKV",
            "与「智能对话」总闸独立；开启后醉酒可用 AI 仓 ChatRWKV（POST /api/chat）",
            "两者都开时醉酒优先走 LLM；仅开本项则走 RWKV。需 AI Runtime 含 chat 资源包",
        ),
    )
    chat_tts_enable: bool = Field(
        default=False,
        description=field_help(
            "酒后对话是否附带语音",
            "走 AI Runtime TTS（RWKV 随 /api/chat；LLM 路径在出字后另调 /tts）",
            "需 AI 仓启用 tts 任务包与音色资源",
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
            "开启后「智能对话」可连续聊；关闭则每句独立",
        ),
    )
    llm_session_user_window: int = Field(
        default=18,
        ge=1,
        le=200,
        description=field_help("用户侧保留的最近消息条数", "越大越连贯，也越费上下文预算"),
    )
    llm_session_group_window: int = Field(
        default=8,
        ge=0,
        le=100,
        description=field_help("群内旁听上下文条数", "0 表示不注入群旁听消息"),
    )
    llm_session_group_ambient_enabled: bool = Field(
        default=True,
        description=field_help("是否注入群旁听上下文", "关闭后仅保留用户与机器人的对话"),
    )
    llm_session_user_ttl_sec: int = Field(
        default=0,
        ge=0,
        le=2592000,
        description=field_help("用户会话过期时间（秒）", "0 表示不过期；到期后清空该用户上下文"),
    )
    llm_session_private_ttl_sec: int = Field(
        default=259200,
        ge=0,
        le=2592000,
        description=field_help("私聊会话过期时间（秒）", "默认约 3 天"),
    )
    llm_session_max_content_len: int = Field(
        default=4000,
        ge=64,
        le=16000,
        description=field_help("单条会话消息写入上限（字符）", "超长消息会截断后再写入上下文"),
    )
    llm_session_strip_vision_enabled: bool = Field(
        default=True,
        description=field_help("写入会话时是否去掉图片内容", "开启可节省上下文，适合纯文本对话"),
    )
    llm_session_summary_enabled: bool = Field(
        default=True,
        description=field_help("是否在会话过长时生成摘要", "达到阈值后压缩旧消息，保留近期原文"),
    )
    llm_session_summary_threshold: int = Field(
        default=40,
        ge=8,
        le=200,
        description=field_help("触发摘要的消息条数阈值", "达到后才会压缩旧上下文"),
    )
    llm_session_summary_keep_messages: int = Field(
        default=16,
        ge=4,
        le=120,
        description=field_help("摘要后仍保留的近期消息条数", "其余由摘要代替"),
    )
    llm_chat_char_budget: int = Field(
        default=12000,
        ge=0,
        le=200000,
        description=field_help(
            "单次闲聊上下文字符预算",
            "0 表示不限制；建议按模型上下文窗口留余量",
        ),
    )
    llm_tools_enabled: bool = Field(
        default=True,
        description=field_help(
            "是否允许智能对话调用工具",
            "需同时开启智能对话总闸；工具由 Bot 内核执行",
        ),
    )
    llm_tools_selective: bool = Field(
        default=True,
        description=field_help(
            "按意图筛选工具",
            "开启后仅在话术命中领域/结构/hints 时下发对应工具，避免一次注入全家桶",
        ),
    )
    llm_tools_max_rounds: int = Field(
        default=4,
        ge=1,
        le=16,
        description=field_help("单次对话最多工具调用轮数", "含模型回复与工具执行的往返次数上限"),
    )
    llm_tools_blacklist: list[str] = Field(
        default_factory=list,
        description=field_help(
            "工具黑名单",
            "可填工具名或领域名（如 sing、memory.search），命中则不下发",
        ),
    )
    llm_tools_desc_max_len: int = Field(
        default=120,
        ge=32,
        le=512,
        description=field_help("工具描述最大长度", "写入模型 schema 前会截断，节省 token"),
    )
    llm_chat_max_concurrency: int = Field(
        default=2,
        ge=1,
        le=64,
        description=field_help(
            "同时进行的闲聊模型请求上限",
            "每个分片 worker 进程独立计数；@ 闲聊与接话分开限流",
        ),
    )
    llm_repeater_group_cooldown_sec: int = Field(
        default=60,
        ge=0,
        le=3600,
        description=field_help(
            "同一群两次接话模型请求的最短间隔（秒）",
            "0 表示不限制群冷却",
        ),
    )
    llm_repeater_strong_cooldown_sec: int = Field(
        default=25,
        ge=0,
        le=3600,
        description=field_help(
            "强场景接话冷却（秒）",
            "0 表示不限制强场景接话冷却",
        ),
    )
    llm_repeater_strong_attempt_rate: float = Field(
        default=0.55,
        ge=0.0,
        le=1.0,
        description=field_help(
            "强场景 LLM 尝试比例",
            "0.55 表示约 55% 的强场景接话会尝试使用 LLM",
        ),
    )
    llm_repeater_max_inflight: int = Field(
        default=2,
        ge=1,
        le=32,
        description=field_help(
            "每个 worker 同时进行的接话模型请求数",
            "与闲聊并发分开计算",
        ),
    )
    llm_repeater_global_rpm: int = Field(
        default=18,
        ge=1,
        le=600,
        description=field_help(
            "全实例每分钟接话模型请求上限",
            "有 Redis 时全局限流；否则按 worker 数分摊",
        ),
    )
    llm_repeater_feedback_enabled: bool = Field(
        default=True,
        description=field_help(
            "是否收集闲聊成功回复，作为复读软反馈",
            "只在回复真正发出后记录",
        ),
    )
    llm_repeater_bias_enabled: bool = Field(
        default=True,
        description=field_help(
            "是否让复读轻微偏向已被闲聊验证过的短回复",
            "保守弱偏置；样本不足时不会生效",
        ),
    )
    llm_repeater_writeback_enabled: bool = Field(
        default=True,
        description=field_help(
            "是否允许将软反馈回写到复读学习语料",
            "仅回写符合条件的软反馈",
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
            "开启后表情包 @ 不会提交智能对话",
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
            "是否启用模型回复输出后过滤",
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
    llm_reply_postprocess_enabled: bool = Field(
        default=False,
        description=field_help(
            "是否启用回复后处理（错别字/拆条）",
            "默认关闭；开启后才应用下方子开关，且不写回语料学习",
        ),
    )
    llm_reply_typo_enabled: bool = Field(
        default=False,
        description=field_help("是否偶尔制造中文近音错别字", "需同时开启回复后处理"),
    )
    llm_reply_typo_rate: float = Field(
        default=0.01,
        description=field_help("单字错别字概率", "0~1，建议 ≤0.03"),
    )
    llm_reply_split_enabled: bool = Field(
        default=False,
        description=field_help("是否按句拆成多条发送", "需同时开启回复后处理"),
    )
    llm_reply_split_max_chars: int = Field(
        default=36,
        description=field_help("拆条单段建议字数上限", "过短会拆得太碎"),
    )
    llm_sticker_fit_enabled: bool = Field(
        default=False,
        description=field_help(
            "是否启用表情 fit 登记与反馈",
            "默认关闭；开启后记录表情反应并按反馈降级",
        ),
    )
    llm_reply_effect_eval_enabled: bool = Field(
        default=False,
        description=field_help(
            "是否异步记录回复效果启发式评分",
            "默认关闭；落盘到 data 目录，不影响主路径延迟",
        ),
    )
    llm_memory_rag_enabled: bool = Field(
        default=True,
        description=field_help(
            "是否启用群记忆检索",
            "开启后可将「记住：…」写入记忆，并按相关度注入对话",
        ),
    )
    llm_expression_inject_enabled: bool = Field(
        default=True,
        description=field_help("是否向对话注入群表达", "关闭后不使用表达库调整回复口气"),
    )
    llm_expression_learn_enabled: bool = Field(
        default=True,
        description=field_help("是否学习群表达", "关闭后不从群消息沉淀表达"),
    )
    llm_expression_auto_promote_enabled: bool = Field(
        default=True,
        description=field_help("是否自动晋升群表达", "关闭后仅保留候选表达，不自动启用"),
    )
    llm_expression_retrieve_limit: int = Field(
        default=5,
        ge=1,
        le=8,
        description=field_help("每次检索的群表达条数", "越大越贴近群内说法，也越占上下文预算"),
    )
    llm_vector_retrieve: VectorRetrieveMode = Field(
        default="hybrid",
        description=field_help(
            "群记忆与知识源的检索方式",
            "hybrid=关键词+向量（默认）；keyword=仅关键词；embedding=纯向量。"
            "向量在 Bot 进程内计算，不请求 Pallas-Bot-AI",
        ),
    )
    llm_embedding_model: str = Field(
        default="stub",
        description=field_help(
            "向量检索使用的 embedding 标识",
            "当前为 Bot 内核本地 hash stub；填 stub 即可，无需 AI 仓或外部 embedding 服务",
        ),
    )
    llm_memory_rag_top_k: int = Field(
        default=3,
        ge=1,
        le=8,
        description=field_help("每次检索注入的记忆条数", "越大越相关，也越占上下文预算"),
    )
    llm_memory_max_per_group: int = Field(
        default=200,
        ge=1,
        le=2000,
        description=field_help("每个群最多保留的记忆条数", "超出后淘汰旧记忆"),
    )
    llm_memory_content_max_len: int = Field(
        default=500,
        ge=64,
        le=4000,
        description=field_help("单条记忆内容上限（字符）", "超长会截断"),
    )
    llm_memory_auto_episode_enabled: bool = Field(
        default=True,
        description=field_help("是否自动沉淀会话片段为记忆", "开启后闲聊结束后可写入群记忆"),
    )
    llm_memory_auto_episode_cooldown_sec: int = Field(
        default=120,
        ge=0,
        le=3600,
        description=field_help("自动沉淀冷却（秒）", "同一会话两次自动写入的最短间隔"),
    )
    llm_memory_graph_extract_enabled: bool = Field(
        default=True,
        description=field_help("是否启用记忆图谱 LLM 抽取", "开启后可用模型从文本提取实体与关系"),
    )
    llm_memory_graph_extract_on_write: bool = Field(
        default=False,
        description=field_help("写入 Episode 后自动抽取", "默认关闭；开启后每次自动沉淀会触发图谱抽取"),
    )
    llm_memory_hiergraph_max_layers: int = Field(
        default=3,
        ge=1,
        le=6,
        description=field_help("分层语义图最大层数", "重建 HierGraph 时向上聚合的层数上限"),
    )
    llm_relationship_notes_enabled: bool = Field(
        default=True,
        description=field_help(
            "是否启用关系备注层",
            "开启后可对 @某人 教导稳定关系（如「记住关系：xx是群主」），随时间衰减",
        ),
    )


def get_llm_webui_config() -> LlmWebuiConfig:
    from pallas.product.llm.config import resolve_chat_tts_enabled, resolve_legacy_rwkv_drunk_chat_enabled

    cfg = get_llm_config()
    mode = normalize_repeater_mode_for_webui(cfg.llm_repeater_mode)
    return LlmWebuiConfig(
        ai_server_host=cfg.ai_server_host,
        ai_server_port=cfg.ai_server_port,
        llm_chat_enabled=cfg.llm_chat_enabled,
        chat_enable=resolve_legacy_rwkv_drunk_chat_enabled(),
        chat_tts_enable=resolve_chat_tts_enabled(),
        llm_repeater_mode=mode,  # type: ignore[arg-type]
        llm_polish_lite_sample_rate=cfg.llm_polish_lite_sample_rate,
        llm_governance_enabled=cfg.llm_governance_enabled,
        llm_session_enabled=cfg.llm_session_enabled,
        llm_session_user_window=cfg.llm_session_user_window,
        llm_session_group_window=cfg.llm_session_group_window,
        llm_session_group_ambient_enabled=cfg.llm_session_group_ambient_enabled,
        llm_session_user_ttl_sec=cfg.llm_session_user_ttl_sec,
        llm_session_private_ttl_sec=cfg.llm_session_private_ttl_sec,
        llm_session_max_content_len=cfg.llm_session_max_content_len,
        llm_session_strip_vision_enabled=cfg.llm_session_strip_vision_enabled,
        llm_session_summary_enabled=cfg.llm_session_summary_enabled,
        llm_session_summary_threshold=cfg.llm_session_summary_threshold,
        llm_session_summary_keep_messages=cfg.llm_session_summary_keep_messages,
        llm_chat_char_budget=cfg.llm_chat_char_budget,
        llm_tools_enabled=cfg.llm_tools_enabled,
        llm_tools_selective=cfg.llm_tools_selective,
        llm_tools_max_rounds=cfg.llm_tools_max_rounds,
        llm_tools_blacklist=list(cfg.llm_tools_blacklist or []),
        llm_tools_desc_max_len=cfg.llm_tools_desc_max_len,
        llm_chat_max_concurrency=cfg.llm_chat_max_concurrency,
        llm_repeater_group_cooldown_sec=cfg.llm_repeater_group_cooldown_sec,
        llm_repeater_strong_cooldown_sec=cfg.llm_repeater_strong_cooldown_sec,
        llm_repeater_strong_attempt_rate=cfg.llm_repeater_strong_attempt_rate,
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
        llm_reply_postprocess_enabled=cfg.llm_reply_postprocess_enabled,
        llm_reply_typo_enabled=cfg.llm_reply_typo_enabled,
        llm_reply_typo_rate=cfg.llm_reply_typo_rate,
        llm_reply_split_enabled=cfg.llm_reply_split_enabled,
        llm_reply_split_max_chars=cfg.llm_reply_split_max_chars,
        llm_sticker_fit_enabled=cfg.llm_sticker_fit_enabled,
        llm_reply_effect_eval_enabled=cfg.llm_reply_effect_eval_enabled,
        llm_memory_rag_enabled=cfg.llm_memory_rag_enabled,
        llm_expression_inject_enabled=cfg.llm_expression_inject_enabled,
        llm_expression_learn_enabled=cfg.llm_expression_learn_enabled,
        llm_expression_auto_promote_enabled=cfg.llm_expression_auto_promote_enabled,
        llm_expression_retrieve_limit=cfg.llm_expression_retrieve_limit,
        llm_vector_retrieve=cfg.llm_vector_retrieve,
        llm_embedding_model=cfg.llm_embedding_model,
        llm_memory_rag_top_k=cfg.llm_memory_rag_top_k,
        llm_memory_max_per_group=cfg.llm_memory_max_per_group,
        llm_memory_content_max_len=cfg.llm_memory_content_max_len,
        llm_memory_auto_episode_enabled=cfg.llm_memory_auto_episode_enabled,
        llm_memory_auto_episode_cooldown_sec=cfg.llm_memory_auto_episode_cooldown_sec,
        llm_memory_graph_extract_enabled=cfg.llm_memory_graph_extract_enabled,
        llm_memory_graph_extract_on_write=cfg.llm_memory_graph_extract_on_write,
        llm_memory_hiergraph_max_layers=cfg.llm_memory_hiergraph_max_layers,
        llm_relationship_notes_enabled=cfg.llm_relationship_notes_enabled,
    )
