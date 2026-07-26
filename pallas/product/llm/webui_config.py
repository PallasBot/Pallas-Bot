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
    return "select_polish_lite"


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
            "唱歌、语音合成等媒体任务要连到哪台机器",
            "默认 127.0.0.1（本机）。Bot 与媒体服务不在同一台时，填对方 IP 或主机名，例如 192.168.1.10",
            "日常聊天不走这里；改完后建议到「媒体服务」页测连通。与端口一起填才完整",
        ),
    )
    ai_server_port: int = Field(
        default=9099,
        ge=1,
        le=65535,
        description=field_help(
            "媒体服务（唱歌/TTS）在对方机器上监听的端口号",
            "默认 9099，须与 Pallas-Bot-AI 启动端口一致。一般在「媒体服务」页改并同步即可",
            "端口填错会出现连不上、唱歌/语音全失败；与主机地址成对配置",
        ),
    )
    llm_chat_enabled: bool = Field(
        default=False,
        description=field_help(
            "群里能不能用智能对话（@ 牛牛、口令聊天、接话用模型能力）",
            "开=允许智能对话相关能力；关=群内不走智能对话。新人建议先开，并配好「接入」里的提供方",
            "须先在「接入」配置可用模型；本开关只管对话总闸，不负责唱歌/TTS",
        ),
    )
    chat_enable: bool = Field(
        default=False,
        description=field_help(
            "醉酒玩法是否走旧版 AI 仓 RWKV 聊天（与智能对话总闸分开）",
            "开=醉酒可走 AI 仓 ChatRWKV；关=不走这条旧通道。多数人只开「智能对话」即可，本项可保持关",
            "两者都开时醉酒优先走智能对话；仅开本项则走 RWKV。需要 AI Runtime 带上 chat 资源包",
        ),
    )
    chat_tts_enable: bool = Field(
        default=False,
        description=field_help(
            "醉酒回复要不要再念成语音发出去",
            "开=醉酒文字后再合成语音；关=只发文字。要听语音时再开，会多一次媒体请求",
            "依赖媒体服务已启用 TTS 与音色；智能对话路径是出字后再调语音接口",
        ),
    )
    llm_repeater_mode: RepeaterMode = Field(
        default="select_polish_lite",
        description=field_help(
            "群里自动接话时，智能对话怎么参与选句和改口气",
            "推荐默认「选句为主，少数回复轻润色」。不想花钱就选「只用语料」；语料常不够再开「语料缺失时现编」",
            "off=只用语料不调模型；select=有语料时让模型挑一句；"
            "select_polish_lite=多数仍选句，约一成会轻改口气；"
            "select_fallback=选句，语料没有时才现编；fallback=仅语料没有时现编。"
            "现编会多花模型费用",
        ),
    )
    llm_polish_lite_sample_rate: float = Field(
        default=0.12,
        ge=0.0,
        le=1.0,
        description=field_help(
            "「选句+轻润色」模式下，大概多少比例的接话会改口气",
            "默认 0.12（约 12%）。想更稳就调低，例如 0.05；想更活就略调高，一般别超过 0.3",
            "仅在接话模式为「选句为主，少数回复轻润色」时生效；调高会多耗模型额度",
        ),
    )
    llm_governance_enabled: bool = Field(
        default=True,
        description=field_help(
            "是否限制智能对话别刷太勤、单次别写太长",
            "开=限制频率与字数（推荐，活跃群尤其要开）；关=几乎不限，容易刷屏、费额度",
            "关了后群很热闹时可能连发很长回复；一般保持开启",
        ),
    )
    llm_session_enabled: bool = Field(
        default=True,
        description=field_help(
            "智能对话是否记住刚才聊过的内容，能连续接话",
            "开=能多轮接着聊（推荐）；关=每句当新对话，不记得上文",
            "关闭后下方「上下文条数」等会话细项基本不再起作用",
        ),
    )
    llm_session_user_window: int = Field(
        default=18,
        ge=1,
        le=200,
        description=field_help(
            "和同一用户聊天时，最多记住最近几条消息",
            "默认 18。觉得牛牛总忘前文可调到 24～30；觉得回复慢或费额度可降到 10～12",
            "条数越大越连贯，也越占上下文预算、越费钱；需开启「记住多轮上下文」",
        ),
    )
    llm_session_group_window: int = Field(
        default=8,
        ge=0,
        le=100,
        description=field_help(
            "接话时顺便参考群里最近几条旁听消息（别人的闲聊）",
            "默认 8。0=完全不看群里别人在说什么。想更懂群气氛可略增，但别太大",
            "须同时开启「注入群旁听上下文」；条数过大会占预算、还可能把无关闲聊带进回复",
        ),
    )
    llm_session_group_ambient_enabled: bool = Field(
        default=True,
        description=field_help(
            "要不要把群里别人的近期消息也塞进上下文（旁听）",
            "开=回复时能参考群气氛（推荐）；关=只看你和牛牛的对话，不看其他人",
            "关闭后「群旁听条数」无效；适合私密或怕串台的场景",
        ),
    )
    llm_session_user_ttl_sec: int = Field(
        default=0,
        ge=0,
        le=2592000,
        description=field_help(
            "群聊里和某用户的会话多久不用就清空（秒）",
            "默认 0=不过期。想隔一段时间自动「失忆」可填秒数，例如 86400≈1 天、604800≈7 天",
            "到期后该用户上下文清空，需重新聊起；0 表示一直保留到被摘要/截断规则处理",
        ),
    )
    llm_session_private_ttl_sec: int = Field(
        default=259200,
        ge=0,
        le=2592000,
        description=field_help(
            "私聊会话多久不用就清空（秒）",
            "默认 259200（约 3 天）。想更久记住可调大；想更常「重新开始」可调小。0=不过期",
            "仅影响私聊；与群聊用户 TTL 相互独立",
        ),
    )
    llm_session_max_content_len: int = Field(
        default=4000,
        ge=64,
        le=16000,
        description=field_help(
            "写入会话记忆时，单条消息最多留多少字",
            "默认 4000。有人贴超长文时可略增；想省预算可降到 2000。超长会截断后再记住",
            "截断只影响上下文记忆，不等于群里收不到原消息",
        ),
    )
    llm_session_strip_vision_enabled: bool = Field(
        default=True,
        description=field_help(
            "记会话时要不要丢掉图片内容，只留文字",
            "开=不把图片塞进上下文（省预算，纯文字聊天推荐）；关=尽量保留图片信息（更费、需模型支持看图）",
            "多数群聊保持开启即可；需要根据图片连续追问时再关",
        ),
    )
    llm_session_summary_enabled: bool = Field(
        default=True,
        description=field_help(
            "聊太长时要不要把旧消息压成摘要，腾出空间",
            "开=达到条数后自动摘要旧内容（推荐长聊）；关=不摘要，旧消息可能被硬丢掉或占满预算",
            "摘要会额外调用一次模型，有少量费用；短聊可关",
        ),
    )
    llm_session_summary_threshold: int = Field(
        default=40,
        ge=8,
        le=200,
        description=field_help(
            "会话里攒到多少条消息才开始做摘要",
            "默认 40。聊天很长、常忘前文可调低（如 24）；想少花摘要费用可调高",
            "须开启「会话过长时生成摘要」；过低会频繁摘要、多花钱",
        ),
    )
    llm_session_summary_keep_messages: int = Field(
        default=16,
        ge=4,
        le=120,
        description=field_help(
            "做完摘要后，最近几条原文仍完整保留",
            "默认 16。想紧接刚才几句就略增；想更省预算就略减（别小于 4）",
            "更早的内容靠摘要概括；须开启摘要功能",
        ),
    )
    llm_speak_perception_enabled: bool = Field(
        default=True,
        description=field_help(
            "除了 @，还要不要靠别名、气氛去判断该不该开口",
            "开=可识别「牛牛」等称呼，也可偶尔未点名插嘴；关=只有 @ / 明确点名才进智能对话",
            "关闭后，别名提及与氛围插嘴（ambient）相关开关都不再生效",
        ),
    )
    llm_speak_mention_enabled: bool = Field(
        default=True,
        description=field_help(
            "群里喊了牛牛的别名（不必 @）时，要不要当点名进对话",
            "开=出现「牛牛」等自称就进智能对话；关=必须 @ 才理你",
            "须开启「发言感知」；别名太短易误触，可调下方最短长度",
        ),
    )
    llm_speak_ambient_enabled: bool = Field(
        default=True,
        description=field_help(
            "没人点名时，要不要按气氛偶尔插一句（ambient=未点名插嘴）",
            "开=可能偶尔接话；关=绝不主动插嘴。怕刷屏就关，或把概率调很低",
            "须开启发言感知；仍受必要度分、概率与冷却约束，空回复可静默不发",
        ),
    )
    llm_speak_ambient_rate: float = Field(
        default=0.08,
        ge=0.0,
        le=1.0,
        description=field_help(
            "氛围插嘴在「值得说」之后，真正发出去的概率",
            "默认 0.08（约 8%）。想更安静填 0.02～0.05；想更活泼可到 0.15，别轻易超过 0.3",
            "先过最低必要度分，再按此比例抽签；调高会更吵、也可能更费模型",
        ),
    )
    llm_speak_ambient_min_score: int = Field(
        default=35,
        ge=0,
        le=100,
        description=field_help(
            "气氛分不够高时干脆不插嘴（0～100）",
            "默认 35。想更挑场景再插嘴就调高（如 50）；想更容易插嘴就调低（如 20）",
            "低于此分直接跳过，不会走到概率抽签",
        ),
    )
    llm_speak_ambient_cooldown_sec: int = Field(
        default=120,
        ge=0,
        le=3600,
        description=field_help(
            "同一群两次氛围插嘴至少隔多少秒",
            "默认 120（2 分钟）。怕连插就调大；0=不冷却（容易刷屏，慎用）",
            "只约束 ambient 插嘴，不影响 @ / 别名硬触发",
        ),
    )
    llm_speak_min_alias_len: int = Field(
        default=2,
        ge=1,
        le=8,
        description=field_help(
            "别名至少几个字才算「喊到牛牛」",
            "默认 2。单字别名易误触，建议 ≥2；若别名本身很长可保持默认",
            "过短（如 1）容易把无关字当成点名",
        ),
    )
    llm_speak_followup_enabled: bool = Field(
        default=True,
        description=field_help(
            "@ 或喊别名之后，短时间内还要不要免唤醒接着聊",
            "开=点名后一小段时间里同一用户说话可直接接（更像连续聊）；关=每句都要再点名",
            "时长由下方「软窗」与「最长总时长」控制",
        ),
    )
    llm_speak_followup_window_sec: int = Field(
        default=45,
        ge=0,
        le=600,
        description=field_help(
            "每次硬触发后，免唤醒续聊保持多久（秒）",
            "默认 45。聊得慢可调到 60～90；想更严格就调短。每次再触发会刷新计时",
            "超时后需再次 @ / 喊别名；另受「最长总时长」封顶",
        ),
    )
    llm_speak_followup_max_total_sec: int = Field(
        default=180,
        ge=0,
        le=3600,
        description=field_help(
            "从第一次点名起，续聊软窗最多能拖多久（秒）",
            "默认 180（3 分钟）。防止一直刷新软窗无限续聊。想更长可调大，0=不按总时长封顶（慎用）",
            "与单次软窗配合：先触达哪个限制就先停",
        ),
    )
    llm_chat_char_budget: int = Field(
        default=12000,
        ge=0,
        le=200000,
        description=field_help(
            "单次智能对话最多塞进多少字符的上下文（记忆、旁听、工具说明等合计）",
            "默认 12000。模型上下文小就调低；上下文很大可略增。0=不限制（易超模型上限报错）",
            "建议按所用模型窗口留余量；过大浪费费用，过小会丢记忆",
        ),
    )
    llm_tools_enabled: bool = Field(
        default=True,
        description=field_help(
            "智能对话能不能调用工具（搜网页、唱歌、查记忆等）",
            "开=允许按需用工具；关=只聊天、不调工具。需要「搜一下」或点歌等能力时保持开",
            "须同时开启智能对话总闸；工具在 Bot 内核执行。联网还要填搜索地址与密钥",
        ),
    )
    llm_tools_selective: bool = Field(
        default=True,
        description=field_help(
            "是不是只把「话里用得上」的工具拿给模型，而不是一股脑全给",
            "开=按意图筛选（推荐，更省、更稳）；关=更容易把大量工具都塞给模型，费额度且易乱调",
            "开启后未命中硬规则时，还可配合「软召回」补少量候选",
        ),
    )
    llm_tools_soft_recall_enabled: bool = Field(
        default=True,
        description=field_help(
            "话术没明确命中工具时，要不要按相似度再补几个候选工具",
            "开=硬规则没命中时，仍可能带上少量相关工具（推荐）；关=未命中就不带工具",
            "依赖「按意图筛选工具」；缺必填参数时会先追问，不会瞎调",
        ),
    )
    llm_tools_soft_recall_min_score: int = Field(
        default=6,
        ge=1,
        le=32,
        description=field_help(
            "软召回时，相关度分不够高就不带这个工具",
            "默认 6。想更严格（少带工具）调高；想更容易带上工具调低",
            "分过低会几乎不召回；过高可能漏掉该用的工具",
        ),
    )
    llm_tools_soft_recall_max_candidates: int = Field(
        default=3,
        ge=1,
        le=8,
        description=field_help(
            "软召回一次最多再带几个工具候选",
            "默认 3。工具很多时别开太大，否则又变回「工具池太大」",
            "同分都很低时不会硬凑到上限",
        ),
    )
    llm_tools_max_rounds: int = Field(
        default=4,
        ge=1,
        le=16,
        description=field_help(
            "一句话里，模型和工具来回最多几轮",
            "默认 4。复杂多步任务可调到 6～8；想省费用、防死循环保持 3～4",
            "轮数含「模型想调工具 → 执行 → 再回复」；过大可能拖很久、费用高",
        ),
    )
    llm_tools_blacklist: list[str] = Field(
        default_factory=list,
        description=field_help(
            "哪些工具或整类能力绝对不给模型用",
            "可填工具名或领域名，例如 sing、memory.search。多个用列表配置。留空=不额外拉黑",
            "命中后该工具不会下发；误填名字等于没拉黑，可到「工具」页对照目录",
        ),
    )
    llm_tools_desc_max_len: int = Field(
        default=120,
        ge=32,
        le=512,
        description=field_help(
            "发给模型的工具说明最长多少字（多了截断）",
            "默认 120。说明太短模型可能用错工具可略增；想省 token 保持默认或略减",
            "只影响写入模型的说明长度，不改工具本身功能",
        ),
    )
    web_search_api_url: str = Field(
        default="",
        description=field_help(
            "群里说「搜一下…」时，实际请求哪个搜索接口地址",
            "推荐填完整 URL：https://api.tavily.com/search（必须带 /search，不要只填域名）。留空=不能联网搜",
            '也可填其它兼容接口：POST，JSON 带 {"query": "…"}。须与密钥一起填，并开启「允许调用工具」',
        ),
    )
    tavily_api_key: str = Field(
        default="",
        description=field_help(
            "联网搜索接口的鉴权密钥（密码）",
            "到 app.tavily.com 注册后复制 Key（常见形如 tvly-…）。与搜索地址成对填写，留空则搜不了",
            "请求时以 Authorization: Bearer 发送。密钥勿发到群里；还须开启工具能力",
        ),
        json_schema_extra={"secret": True},
    )
    llm_chat_max_concurrency: int = Field(
        default=2,
        ge=1,
        le=64,
        description=field_help(
            "同一时刻最多允许多少路智能对话请求在跑",
            "默认 2。机器/额度紧张保持 1～2；很闲且额度充足可略增。过大易把接口打满、全员变慢",
            "每个分片 worker 各自计数；@ 对话与接话限流分开算",
        ),
    )
    llm_repeater_group_cooldown_sec: int = Field(
        default=60,
        ge=0,
        le=3600,
        description=field_help(
            "同一群两次「接话用模型」至少隔多少秒",
            "默认 60。活跃群想少花钱可调大；0=不限制群冷却（可能很勤、很费）",
            "只约束接话模型请求，不等于完全不复读语料",
        ),
    )
    llm_repeater_strong_cooldown_sec: int = Field(
        default=25,
        ge=0,
        le=3600,
        description=field_help(
            "强场景接话（更值得认真回的那种）两次用模型的最短间隔",
            "默认 25 秒。想更克制调大；0=不限制。一般可小于普通群冷却",
            "与普通群冷却配合：强场景有单独节奏，避免连发烧额度",
        ),
    )
    llm_repeater_strong_attempt_rate: float = Field(
        default=0.55,
        ge=0.0,
        le=1.0,
        description=field_help(
            "强场景里，大概多大比例会真的去调模型接话",
            "默认 0.55（约 55%）。想更省调低；想更常认真回可调高到 0.7～0.8",
            "未抽中时仍可能用语料等方式接话，但不走这次模型请求",
        ),
    )
    llm_repeater_max_inflight: int = Field(
        default=2,
        ge=1,
        le=32,
        description=field_help(
            "每个 worker 同时最多跑几路「接话」模型请求",
            "默认 2。与「智能对话并发」分开。机器吃力就降到 1；过大易拖慢整机",
            "和全局限流一起卡住高峰，避免接话把额度打爆",
        ),
    )
    llm_repeater_global_rpm: int = Field(
        default=18,
        ge=1,
        le=600,
        description=field_help(
            "整套实例每分钟最多多少次接话模型请求",
            "默认 18。多群很吵可调低省钱；额度宽裕且延迟敏感可略增。别一上来拉到几百",
            "配了 Redis 时是真正全局限流；否则按 worker 数量分摊估算",
        ),
    )
    llm_repeater_feedback_enabled: bool = Field(
        default=True,
        description=field_help(
            "智能对话成功发出的短回复，要不要记下来反哺以后的接话",
            "开=回复真正发出后才记录（推荐）；关=不收集这类反馈",
            "只记成功发出的内容；坏回复可在会话页排除，避免污染",
        ),
    )
    llm_repeater_bias_enabled: bool = Field(
        default=True,
        description=field_help(
            "接话选句时，要不要略微偏向「以前智能对话验证过」的短句",
            "开=有足够样本时轻微偏向（保守）；关=选句完全不看这些反馈",
            "样本太少时不会强行生效；依赖上方「收集反哺」",
        ),
    )
    llm_repeater_writeback_enabled: bool = Field(
        default=True,
        description=field_help(
            "合格的软反馈要不要写进接话学习语料，让以后更能复用",
            "开=符合条件才回写（进阶，可保持开）；关=只影响当场打分，不进语料库",
            "写回前建议先在会话页处理好坏样本；乱写回会让语料变怪",
        ),
    )
    conversation_feature_level: ConversationFeatureLevel = Field(
        default="",
        description=field_help(
            "对话内核整体能力开到哪一档（一般交给自动推断即可）",
            "留空=按现有开关自动推断（推荐）。需要完整能力时选 full_conversation_kernel。"
            "legacy_repeater / repeater_plus_decision 仅兼容旧配置，不建议新开",
            "乱选旧档可能导致部分新功能不可用；不确定就留空",
        ),
    )
    llm_reply_gate_enabled: bool = Field(
        default=True,
        description=field_help(
            "纯表情包等没实质内容的 @，要不要直接忽略、别浪费一次对话",
            "开=过滤无意义 @（推荐）；关=表情包 @ 也会进智能对话、花钱",
            "开启后这类 @ 不会提交模型；想逗着玩可临时关掉",
        ),
    )
    llm_current_turn_decision_enabled: bool = Field(
        default=False,
        description=field_help(
            "回复前要不要先用小模型想一下「回不回、怎么回、要不要用工具」",
            "开=多一次决策请求，再决定动作；关=走原来的直接回复流程（默认，不额外花钱）",
            "关闭时不会发起额外模型请求。开启后请到「接入 → 任务编排」里给「本轮动作决策」选提供方与模型",
        ),
    )
    llm_current_turn_decision_model: str = Field(
        default="",
        description=field_help(
            "旧版「本轮动作决策」单独填模型名的遗留项",
            "新配置请到「任务编排 → 本轮动作决策」设置，这里留空即可",
            "仅兼容读旧配置；两边都填时以任务编排为准更清晰",
        ),
    )
    llm_chat_queue_merge: bool = Field(
        default=True,
        description=field_help(
            "冷却期间有人连发多条 @，要不要合并成只处理最后一次",
            "开=冷却内连发只保留最后一次（省钱、少刷屏，推荐）；关=每条都排队处理，更费更吵",
            "与频率限制配合；关闭后高峰期请求量会明显上升",
        ),
    )
    llm_output_filter_enabled: bool = Field(
        default=True,
        description=field_help(
            "模型写出客服腔、乱邀约等怪句时，要不要拦截后再处理",
            "开=启用输出过滤（推荐）；关=模型原文基本照发，可能出现生硬客服腔",
            "接话任务命中拦截时优先退回语料原文；对话任务可能静默不发",
        ),
    )
    llm_output_filter_chat_hard_phrases: list[str] = Field(
        default_factory=default_output_filter_chat_hard_phrases,
        description=field_help(
            "对话/接话里一旦出现就硬拦的词句列表",
            'JSON 字符串数组，例如 ["您好，我是客服"]。命中后：接话退回语料，智能对话可不发出',
            "改词表前先看默认项；清成空数组等于几乎不硬拦（不推荐）",
        ),
    )
    llm_output_filter_chat_soft_phrases: list[str] = Field(
        default_factory=default_output_filter_chat_soft_phrases,
        description=field_help(
            "对话/接话里软拦截的词句（处理方式与硬拦类似，方便分批下线）",
            "同样是 JSON 字符串数组。先把可疑说法放软表观察，确认后再挪到硬表",
            "须开启「回复输出过滤」；与硬拦列表一起生效",
        ),
    )
    llm_output_filter_polish_lite_hard_phrases: list[str] = Field(
        default_factory=default_output_filter_polish_lite_hard_phrases,
        description=field_help(
            "轻润色专用的额外硬拦词（只影响「轻改口气」那条路径）",
            "JSON 数组；会与上方对话硬拦合并后用于轻润色。只拦润色结果时可改这里",
            "接话模式不是轻润色时，这些额外词基本用不上",
        ),
    )
    llm_output_filter_polish_lite_soft_phrases: list[str] = Field(
        default_factory=default_output_filter_polish_lite_soft_phrases,
        description=field_help(
            "轻润色专用的额外软拦词",
            "JSON 数组；与对话软拦合并后用于轻润色。同样建议先软后硬",
            "须开启输出过滤；仅作用于轻润色路径",
        ),
    )
    llm_persona_output_firewall: dict[str, object] = Field(
        default_factory=lambda: {
            "version": 1,
            "enabled": False,
            "severity": "strict",
            "strategy": "retry_then_fallback",
            "max_retries": 1,
        },
        description=field_help(
            "要不要检查回复是否人设崩了（泄提示词、舞台旁白、自称模型等）",
            "JSON 对象；默认 enabled=false。要更严人设时把 enabled 设为 true，其余保持默认即可",
            "开启后违规最多重说一次，仍不行则按策略回落；会多一次模型请求",
        ),
    )
    llm_reply_postprocess_enabled: bool = Field(
        default=False,
        description=field_help(
            "发出前要不要做「错别字 / 拆成多条」等后处理",
            "开=才会应用下面的错别字、拆条等子开关；关=不做这些花样（默认）",
            "后处理结果不写回语料学习；想玩味道再开，日常可关",
        ),
    )
    llm_reply_typo_enabled: bool = Field(
        default=False,
        description=field_help(
            "要不要偶尔把字改成近音错别字，显得更随意",
            "开=按下方概率制造错字；关=不故意写错。须先开启「回复后处理」",
            "概率建议很小；过大阅读体验会很差",
        ),
    )
    llm_reply_typo_rate: float = Field(
        default=0.01,
        description=field_help(
            "每个字被改成近音错别字的概率（0～1）",
            "默认 0.01。建议 ≤0.03；0.1 已经很花。须同时开启后处理与「偶发错别字」",
            "调太高群友会觉得牛牛打字障碍",
        ),
    )
    llm_reply_split_enabled: bool = Field(
        default=False,
        description=field_help(
            "长回复要不要按句子拆成多条气泡发送",
            "开=拆成多条；关=一条发完。须先开启回复后处理。想更像真人连发可开",
            "拆太碎会刷屏，配合下方字数上限一起调",
        ),
    )
    llm_reply_split_max_chars: int = Field(
        default=36,
        description=field_help(
            "拆条时，每一小段大概不超过多少字",
            "默认 36。想少拆几条就调大（如 60）；过小（如 10）会拆得很碎、很刷屏",
            "须开启后处理与「按句拆条」",
        ),
    )
    llm_sticker_fit_enabled: bool = Field(
        default=False,
        description=field_help(
            "要不要记录表情反应合不合适，并按反馈慢慢降级差表情",
            "开=登记表情适配与反馈；关=不做这套（默认）。表情玩法有人维护时再开",
            "默认关闭；开启后按反馈降级，不影响主聊天延迟太多",
        ),
    )
    llm_reply_effect_eval_enabled: bool = Field(
        default=False,
        description=field_help(
            "要不要在后台给回复打个效果分，方便以后分析",
            "开=异步记分到数据目录；关=不记（默认）。一般运维可保持关",
            "不影响主路径快慢；分数是启发式，不是精确质量分",
        ),
    )
    llm_reply_style_variants: dict[str, object] = Field(
        default_factory=lambda: {
            "version": 1,
            "enabled": True,
            "base_probability": 0.25,
            "affect_styles": {
                "warm": ["playful", "follow"],
                "cool": ["cool", "direct"],
                "chaotic": ["playful", "rhetorical"],
                "assertive": ["direct", "rhetorical"],
                "default": ["cool", "playful", "direct", "rhetorical", "follow"],
            },
        },
        description=field_help(
            "按当前情绪，临时换一种口气说话（不影响长期人设/牛格）",
            "用表单开关即可：开=按概率抽一个口气；关=不用变体。默认约 25% 触发。可选口气在表单里点选",
            "只影响当轮提示，不写入静态人设。没有情感数据时走 default 那组口气",
        ),
    )
    llm_memory_rag_enabled: bool = Field(
        default=True,
        description=field_help(
            "群里「记住：…」以及相关记忆，要不要检索后塞进对话",
            "开=可写入并按相关度注入（推荐）；关=不走群记忆检索，牛牛更「健忘」",
            "关闭后下方记忆条数、自动沉淀等细项基本不再参与对话注入",
        ),
    )
    llm_expression_inject_enabled: bool = Field(
        default=True,
        description=field_help(
            "回复时要不要参考本群常用说法来调口气",
            "开=注入群表达（更像本群）；关=不用表达库。想统一官方腔可关",
            "与「学习群表达」独立：关注入仍可能在后台学习，只是当轮不用",
        ),
    )
    llm_expression_learn_enabled: bool = Field(
        default=True,
        description=field_help(
            "要不要从群消息里慢慢学本群口头禅/说法",
            "开=持续沉淀候选表达（推荐）；关=不再学习新说法",
            "学到的内容是否自动启用，看「自动晋升」开关",
        ),
    )
    llm_expression_auto_promote_enabled: bool = Field(
        default=True,
        description=field_help(
            "学到的群表达要不要自动变成正式可用",
            "开=达标后自动启用；关=只留在候选，需人工晋升。怕学坏梗可先关",
            "依赖学习开关；关闭后注入侧只能用已晋升的表达",
        ),
    )
    llm_expression_retrieve_limit: int = Field(
        default=5,
        ge=1,
        le=8,
        description=field_help(
            "每次回复最多带几条群表达进上下文",
            "默认 5。想更贴群可到 6～8；想省预算降到 3～4",
            "条数越大越占字符预算；须开启「注入群表达」才有体感",
        ),
    )
    llm_vector_retrieve: VectorRetrieveMode = Field(
        default="hybrid",
        description=field_help(
            "查群记忆/知识时，用关键词、向量，还是两者一起",
            "推荐 hybrid（关键词+向量）。只要关键字搜选 keyword；更偏语义相似选 embedding。"
            "vector 为兼容旧名，效果近 embedding",
            "向量在 Bot 进程内算，不请求 Pallas-Bot-AI；换模式后新旧记忆召回观感可能不同",
        ),
    )
    llm_embedding_model: str = Field(
        default="stub",
        description=field_help(
            "向量检索用哪套本地向量标识（一般不用改）",
            "当前填 stub 即可：Bot 内核本地哈希占位，不需要外接 embedding 服务",
            "乱改成不存在的名字可能导致向量检索异常；保持 stub",
        ),
    )
    llm_memory_rag_top_k: int = Field(
        default=3,
        ge=1,
        le=8,
        description=field_help(
            "每次对话最多注入几条相关记忆",
            "默认 3。记性不够可调到 4～5；想省预算保持 2～3",
            "越大越相关也可能越吵、越占预算；须开启群记忆检索",
        ),
    )
    llm_memory_max_per_group: int = Field(
        default=200,
        ge=1,
        le=2000,
        description=field_help(
            "每个群最多存多少条记忆",
            "默认 200。记忆很多的群可调到 500；磁盘/检索压力大就调低。超出会淘汰旧记忆",
            "调太小会频繁丢旧记忆；调太大检索变慢",
        ),
    )
    llm_memory_content_max_len: int = Field(
        default=500,
        ge=64,
        le=4000,
        description=field_help(
            "单条记忆正文最多多少字，超长截断",
            "默认 500。常记长文可调到 800～1000；想条目更短更密可降到 300",
            "截断后只保留前段；过长条目会浪费检索与注入预算",
        ),
    )
    llm_memory_auto_episode_enabled: bool = Field(
        default=True,
        description=field_help(
            "聊完一轮后，要不要自动把片段沉淀进群记忆",
            "开=对话结束后可能自动写入（推荐）；关=只靠人工「记住：」",
            "写入节奏受下方冷却限制；开启图谱「写入后抽取」还会多耗模型",
        ),
    )
    llm_memory_auto_episode_cooldown_sec: int = Field(
        default=120,
        ge=0,
        le=3600,
        description=field_help(
            "同一会话两次自动沉淀记忆至少隔多少秒",
            "默认 120。想少记一点调大；0=不冷却（可能记太勤）。须开启自动沉淀",
            "过密写入会产生大量相似记忆，检索变吵",
        ),
    )
    llm_memory_graph_extract_enabled: bool = Field(
        default=True,
        description=field_help(
            "要不要用模型从文字里抽「谁和谁有什么关系」做成记忆图谱",
            "开=允许图谱抽取；关=不做实体关系抽取。需要关系网时再开，会花模型费用",
            "「写入后自动抽取」另开才会每次沉淀都抽；本项是总能力开关",
        ),
    )
    llm_memory_graph_extract_on_write: bool = Field(
        default=False,
        description=field_help(
            "每次自动写入记忆后，要不要立刻跑一次图谱抽取",
            "开=每次自动沉淀都抽（更及时，更费）；关=不自动抽（默认，推荐）",
            "须开启图谱抽取总开关；频繁开启会明显增加模型请求",
        ),
    )
    llm_memory_hiergraph_max_layers: int = Field(
        default=3,
        ge=1,
        le=6,
        description=field_help(
            "分层语义图往上聚合最多几层",
            "默认 3。图很深、想更概括可到 4～5；一般保持 3。重建 HierGraph（分层语义图）时生效",
            "层数过大计算更重，收益未必明显",
        ),
    )
    llm_relationship_notes_enabled: bool = Field(
        default=True,
        description=field_help(
            "能不能教牛牛记住稳定关系（例如「记住关系：xx 是群主」）",
            "开=可用关系备注，并随时间慢慢淡化（推荐）；关=不接受这类关系教导",
            "用法常配合 @ 某人；关闭后已有备注也可能不再参与",
        ),
    )


def get_llm_webui_config() -> LlmWebuiConfig:
    from pallas.core.foundation.config.repo_settings import repo_env_raw_value
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
        llm_speak_perception_enabled=cfg.llm_speak_perception_enabled,
        llm_speak_mention_enabled=cfg.llm_speak_mention_enabled,
        llm_speak_ambient_enabled=cfg.llm_speak_ambient_enabled,
        llm_speak_ambient_rate=cfg.llm_speak_ambient_rate,
        llm_speak_ambient_min_score=cfg.llm_speak_ambient_min_score,
        llm_speak_ambient_cooldown_sec=cfg.llm_speak_ambient_cooldown_sec,
        llm_speak_min_alias_len=cfg.llm_speak_min_alias_len,
        llm_speak_followup_enabled=cfg.llm_speak_followup_enabled,
        llm_speak_followup_window_sec=cfg.llm_speak_followup_window_sec,
        llm_speak_followup_max_total_sec=cfg.llm_speak_followup_max_total_sec,
        llm_chat_char_budget=cfg.llm_chat_char_budget,
        llm_tools_enabled=cfg.llm_tools_enabled,
        llm_tools_selective=cfg.llm_tools_selective,
        llm_tools_soft_recall_enabled=cfg.llm_tools_soft_recall_enabled,
        llm_tools_soft_recall_min_score=cfg.llm_tools_soft_recall_min_score,
        llm_tools_soft_recall_max_candidates=cfg.llm_tools_soft_recall_max_candidates,
        llm_tools_max_rounds=cfg.llm_tools_max_rounds,
        llm_tools_blacklist=list(cfg.llm_tools_blacklist or []),
        llm_tools_desc_max_len=cfg.llm_tools_desc_max_len,
        web_search_api_url=str(repo_env_raw_value("WEB_SEARCH_API_URL") or "").strip(),
        tavily_api_key=str(repo_env_raw_value("TAVILY_API_KEY") or "").strip(),
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
        llm_current_turn_decision_enabled=cfg.llm_current_turn_decision_enabled,
        llm_current_turn_decision_model=cfg.llm_current_turn_decision_model,
        llm_chat_queue_merge=cfg.llm_chat_queue_merge,
        llm_output_filter_enabled=cfg.llm_output_filter_enabled,
        llm_output_filter_chat_hard_phrases=cfg.llm_output_filter_chat_hard_phrases,
        llm_output_filter_chat_soft_phrases=cfg.llm_output_filter_chat_soft_phrases,
        llm_output_filter_polish_lite_hard_phrases=cfg.llm_output_filter_polish_lite_hard_phrases,
        llm_output_filter_polish_lite_soft_phrases=cfg.llm_output_filter_polish_lite_soft_phrases,
        llm_persona_output_firewall=cfg.llm_persona_output_firewall,
        llm_reply_postprocess_enabled=cfg.llm_reply_postprocess_enabled,
        llm_reply_typo_enabled=cfg.llm_reply_typo_enabled,
        llm_reply_typo_rate=cfg.llm_reply_typo_rate,
        llm_reply_split_enabled=cfg.llm_reply_split_enabled,
        llm_reply_split_max_chars=cfg.llm_reply_split_max_chars,
        llm_sticker_fit_enabled=cfg.llm_sticker_fit_enabled,
        llm_reply_effect_eval_enabled=cfg.llm_reply_effect_eval_enabled,
        llm_reply_style_variants=cfg.llm_reply_style_variants,
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
