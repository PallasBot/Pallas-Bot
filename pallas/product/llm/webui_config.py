"""WebUI 通用配置：LLM 全局开关、Bot 内核对话策略与媒体服务地址。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from pallas.console.webui.field_help import field_help
from pallas.console.webui.provider_gateway import ui_provider_gateway
from pallas.product.llm.config import LlmMcpServerConfig, get_llm_config

VectorRetrieveMode = Literal["keyword", "embedding", "hybrid", "vector"]
EmbeddingProviderChoice = Literal["", "stub", "openai", "local"]


def _embedding_provider_choice(raw: object) -> EmbeddingProviderChoice:
    from pallas.product.llm.knowledge.embedding_provider import normalize_embedding_provider_name

    name = normalize_embedding_provider_name(str(raw or ""))
    if name in ("", "stub", "openai", "local"):
        return name  # type: ignore[return-value]
    return ""


ConversationFeatureLevel = Literal["", "legacy_repeater", "repeater_plus_decision", "full_conversation_kernel"]


def default_output_filter_chat_hard_phrases() -> list[str]:
    from pallas.product.llm.output_filter import CHAT_HARD_BLOCK_PHRASES

    return list(CHAT_HARD_BLOCK_PHRASES)


def default_output_filter_chat_soft_phrases() -> list[str]:
    from pallas.product.llm.output_filter import CHAT_SOFT_RETRY_PHRASES

    return list(CHAT_SOFT_RETRY_PHRASES)


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
            "群里能不能用智能对话（@ 牛牛、命令聊天、接话用模型能力）",
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
            "酒后对话出字后，要不要再跟一条语音（侧车 TTS）",
            "开=先发文字，再按下方阈值决定是否念出来；关=酒后只出字。"
            "须已安装「牛牛说」扩展、启用 TTS，并配好媒体服务与音色",
            "与手动「牛牛说」共用 AI Runtime；未达醉酒度/字数阈值时仍只发文字，不会报错刷屏",
        ),
    )
    drunk_tts_min_drunkenness: int = Field(
        default=1,
        ge=0,
        le=100,
        description=field_help(
            "酒后附带语音所需的最低醉酒度",
            "默认 1：该牛在本群至少成功「牛牛喝酒」1 次且尚未醒酒。"
            "醉酒度按「每只牛 × 每个群」计数，每喝一杯 +1；定时醒酒 -1，「牛牛醒一醒」清零",
            "设为 0 表示不卡醉酒度（仍须处于酒后对话路径且总开关开启）；调高则要多喝几杯才念",
        ),
    )
    drunk_tts_min_chars: int = Field(
        default=6,
        ge=0,
        le=2000,
        description=field_help(
            "酒后回文至少多少字才附带语音",
            "默认 6：回文字数（去首尾空白）≥ 此值才 enqueue TTS，避免极短应答也念",
            "与「最低醉酒度」同时满足才会文+音；仅统计本次酒后回复正文",
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
    llm_session_user_storage_window: int = Field(
        default=200,
        ge=1,
        le=1000,
        description=field_help(
            "每个用户最多在存储里保留多少条历史消息（超出后由摘要接管）",
            "默认 200。聊天很长的群可调大；一般保持默认，过大只会占磁盘",
            "与「记忆条数」独立；摘要开启时，超过此窗口的旧内容会先被压缩",
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
        default=24,
        ge=8,
        le=200,
        description=field_help(
            "会话里攒到多少条消息才开始做摘要",
            "默认 24。聊天很长、常忘前文可调低；想少花摘要费用可调高",
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
    llm_session_summary_cooldown_sec: int = Field(
        default=600,
        ge=0,
        le=86400,
        description=field_help(
            "同一会话两次做摘要至少隔多少秒",
            "默认 600（10 分钟）。聊天频繁、常触发摘要可调大减少费用；0=不冷却",
            "只影响摘要触发频率，不影响存储窗口",
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
    llm_speak_ambient_budget_limit: int = Field(
        default=2,
        ge=0,
        le=20,
        description=field_help(
            "同一牛牛账号在同一群的氛围插嘴次数上限",
            "默认 2；0=不限次数，容易刷屏，慎用",
            "只约束未点名 ambient，不影响 @、别名点名和续聊",
        ),
    )
    llm_speak_ambient_budget_window_sec: int = Field(
        default=900,
        ge=60,
        le=86400,
        description=field_help(
            "氛围插嘴预算的统计窗口（秒）",
            "默认 900（15 分钟）；窗口内到上限会保持沉默",
            "与同群冷却一起限制打扰，不影响硬触发",
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
    mcp_servers: list[LlmMcpServerConfig] = Field(
        default_factory=list,
        description=field_help(
            "接入哪些外部 MCP 工具服务器",
            "在「对话配置 → 工具」里增删。stdio 填启动命令；HTTP 还须配置下方允许的 URL 前缀",
            "保存后会重新注册工具目录。command / enabled_tools 为空时按传输类型忽略对应项",
        ),
    )
    llm_mcp_http_allowlist: str = Field(
        default="",
        description=field_help(
            "允许访问的 MCP HTTP 地址前缀（逗号分隔）",
            "仅 transport=http 时需要。例如 http://127.0.0.1:8765 。留空则拒绝所有 HTTP MCP",
            "须与服务器 url 前缀匹配；未列入名单的地址不会连接",
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
            "Repeater 选择语料时，要不要略微偏向「以前智能对话验证过」的短句",
            "开=有足够样本时轻微偏向（保守）；关=本地语料排序完全不看这些反馈",
            "样本太少时不会强行生效；依赖上方「收集反哺」",
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
            "回复前先想一下「回不回、怎么回、要不要用工具」",
            "开=多加一次模型决策请求再决定动作（多一次耗时与费用）；关=走规则判定后直接生成（默认，省一次模型往返）",
            "开启后请到「接入 → 任务编排」里给「本轮动作决策」选提供方与模型",
        ),
    )
    llm_shut_up_silence_enabled: bool = Field(
        default=True,
        description=field_help(
            "群里说「闭嘴」等话，让牛牛随机静默一小段时间再说话",
            "开=听到闭嘴类话术按群静默（推荐）；关=只跳过当前这句，不进入静默",
            "静默期内仍会正常执行命令；说「说话/回话」可提前解除",
        ),
    )
    llm_shut_up_silence_min_sec: int = Field(
        default=30,
        ge=1,
        le=3600,
        description=field_help(
            "一次闭嘴静默的最短时长（秒）",
            "默认 30 秒。实际时长为最短到最长之间随机",
            "上限见下方最大值；范围内随机选取",
        ),
    )
    llm_shut_up_silence_max_sec: int = Field(
        default=300,
        ge=1,
        le=86400,
        description=field_help(
            "一次闭嘴静默的最长时长（秒）",
            "默认 300 秒（5 分钟）。实际时长为最短到最长之间随机",
            "设成与最小值相同则固定不变",
        ),
    )
    llm_chat_queue_merge: bool = Field(
        default=True,
        description=field_help(
            "冷却/排队期连发多条 @，要不要合并成一次回复",
            "开=合并为一次回复（省钱、少刷屏，推荐）；关=逐条排队、每条单独回复，轮到时会引用原消息",
            "与频率限制配合；关闭后高峰期请求量会明显上升",
        ),
    )
    llm_chat_queue_enabled: bool = Field(
        default=True,
        description=field_help(
            "高峰并发占满时，@ 对话要不要进入有界等待队列而非直接跳过",
            "开=显式 @ 请求排队等空位（超时或队满仍可能放弃）；关=维持旧行为，满并发直接不理",
            "与「对话并发上限」配合；被动/复读等低优先级始终不排队",
        ),
    )
    llm_chat_queue_max: int = Field(
        default=8,
        ge=1,
        le=64,
        description=field_help(
            "排队等待的 @ 对话最多允许多少个",
            "默认 8。高峰并发占满时，超出的新请求会挤掉排队最久的旧请求",
            "每个分片 worker 各自计数；太大可能让回复延迟明显",
        ),
    )
    llm_chat_queue_wait_sec: float = Field(
        default=20.0,
        ge=0.1,
        le=120.0,
        description=field_help(
            "排队等空位最多等几秒，超时放弃本次回复",
            "默认 20 秒。等太久用户体验差，等太短等于没排队",
            "只对显式 @ 对话生效",
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
    llm_persona_output_firewall: dict[str, object] = Field(
        default_factory=lambda: {
            "version": 1,
            "enabled": False,
            "severity": "strict",
            "strategy": "retry_then_fallback",
            "max_retries": 1,
        },
        description=field_help(
            "要不要检查回复是否人设崩了（泄提示词、舞台旁白、自称模型、重复垫词）",
            "默认关。要更严人设时再开；表单里可选拦截力度、拦下后先重说还是直接兜底",
            "开启后违规最多再生成一次，仍不行则用安全回复；可能多一次模型费用。工具已执行时不会重跑工具",
        ),
    )
    llm_reply_postprocess_enabled: bool = Field(
        default=False,
        description=field_help(
            "发出前要不要做「错别字 / 省略末尾句号」等后处理",
            "开=才会应用下面的错别字、末尾句号等子开关；关=不做这些花样（默认）",
            "后处理结果不写回语料学习；想玩味道再开，日常可关",
        ),
    )
    llm_reply_trim_terminal_period_enabled: bool = Field(
        default=True,
        description=field_help(
            "短句末尾要不要偶尔不打句号",
            "只作用于 24 字以内的单句陈述；问号、感叹号、多句和长答不动",
            "默认开。关闭后始终保留模型给出的句号",
        ),
    )
    llm_reply_trim_terminal_period_rate: float = Field(
        default=0.9,
        description=field_help(
            "短句省略句号的概率（0～1）",
            "默认 0.9；只在上述短单句条件满足时抽样",
            "设为 0 可保留句号；设为 1 则符合条件时总是省略",
        ),
    )
    llm_reply_split_randomize_enabled: bool = Field(
        default=True,
        description=field_help(
            "短回复要不要偶尔整条一句发出（不打散成多气泡）",
            "开=约按下方概率随机保留整条；关=一律按现有规则拆分",
            "用于缓解「X？ Y」式两气泡模板感；默认开",
        ),
    )
    llm_reply_split_randomize_keep_rate: float = Field(
        default=0.4,
        description=field_help(
            "保留整条不发多气泡的概率（0～1）",
            "默认 0.4；开启随机化时生效",
            "设 0=总是拆分；设 1=短回复基本不拆",
        ),
    )
    llm_bubble_delay_base_sec: float = Field(
        default=0.8,
        description=field_help(
            "气泡间隔基础值（秒）",
            "默认 0.8；与长度无关的固定停顿",
            "间隔 = 基础值 + 字数×每字增量，再乘抖动，上限 3.5 秒",
        ),
    )
    llm_bubble_delay_per_char: float = Field(
        default=0.04,
        description=field_help(
            "气泡间隔每字增量（秒/字符）",
            "默认 0.04；消息越长间隔越长",
            "建议 0.02～0.08；过大长消息会显得很慢",
        ),
    )
    llm_bubble_delay_jitter: float = Field(
        default=0.35,
        description=field_help(
            "气泡间隔抖动（±比例）",
            "默认 0.35；模拟真人打字随机停顿",
            "设 0=完全固定；建议不超过 0.9",
        ),
    )
    llm_reply_mention_cooldown_sec: int = Field(
        default=900,
        description=field_help(
            "群内 @ 某位成员的最短间隔（秒）",
            "默认 900 秒。只限制模型主动选择的 @，引用和普通回复不受影响",
            "设为 0 取消间隔；建议保持较长，避免把群聊变成提醒机器人",
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
    llm_sticker_fit_enabled: bool = Field(
        default=False,
        description=field_help(
            "要不要记录表情反应合不合适，并按反馈慢慢降级差表情",
            "开=登记表情适配与反馈；关=不做这套（默认）。表情玩法有人维护时再开",
            "默认关闭；开启后按反馈降级，不影响主聊天延迟太多",
        ),
    )
    llm_chat_sticker_enabled: bool = Field(
        default=True,
        description=field_help(
            "Bot 文本按需发送 Repeater 表情图",
            "群消息送达后按冷却和候选情况决定是否配图；没有可用缓存时只发文字",
            "默认开启；不影响 QQ 气泡 Reaction",
        ),
    )
    llm_chat_sticker_cooldown_sec: int = Field(
        default=90,
        description=field_help("Bot 表情图冷却秒数", "同一群两次 Bot 表情图之间至少间隔多久；0 只保留同图去重"),
    )
    llm_chat_sticker_max_per_hour: int = Field(
        default=8,
        ge=0,
        le=1000,
        description=field_help("Bot 表情图每小时上限", "每个群每小时最多发送多少张跟随表情图；0 表示关闭。"),
    )
    llm_sticker_vision_enabled: bool = Field(
        default=False,
        description=field_help(
            "视觉模型选表情图",
            "仅在 LLM 决定贴图且有至少 3 张语义候选时调用。配置的视觉模型也会复用为「聊天看图」，"
            "主对话模型不支持图片时用它把图转成文字描述。",
            "需要在「接入 → 任务编排」里给「视觉选图」选提供方与模型（带 image 能力）",
        ),
    )
    llm_sticker_vision_candidate_count: int = Field(
        default=4,
        ge=3,
        le=6,
        description=field_help("视觉选图候选数", "默认 4；候选越多越准，但更耗视觉模型额度。"),
    )
    llm_sticker_vision_timeout_sec: float = Field(
        default=15.0,
        ge=1.0,
        le=30.0,
        description=field_help("视觉选图超时秒数", "超时回退 Repeater 语义候选，不影响文字回复。"),
    )
    llm_sticker_vision_max_per_hour: int = Field(
        default=12,
        ge=0,
        le=1000,
        description=field_help("视觉选图每小时上限", "0 表示关闭视觉选图；达到上限时直接回退 Repeater 候选。"),
    )
    llm_sticker_label_backfill_enabled: bool = Field(
        default=True,
        description=field_help("标签每日回填", "后台按每日预算为缺失标签的缓存图补建语义标签。"),
    )
    llm_sticker_label_backfill_daily_limit: int = Field(
        default=200,
        ge=0,
        le=2000,
        description=field_help("标签回填每日预算", "每天最多为多少张图调用视觉模型打标签；0 表示关闭。"),
    )
    llm_sticker_label_realtime_daily_limit: int = Field(
        default=300,
        ge=0,
        le=2000,
        description=field_help(
            "标签实时标注每日预算",
            "默认 300。新收到的表情立即识别语义、存入缓存；0=关闭实时标注",
            "超限后当天不再实时标注，只保留回填路径",
        ),
    )
    llm_semantic_style_realtime_daily_limit: int = Field(
        default=600,
        ge=0,
        le=50000,
        description=field_help(
            "语义风格标注每日预算",
            "默认 600。群洞察处理器从 message 表重建成对样本后调用 LLM 标注语料的每日上限；0 表示不限制",
            "到达上限后当天不再消费新的语义标注任务，游标保留，次日恢复",
        ),
    )
    llm_sticker_habit_enabled: bool = Field(
        default=True,
        description=field_help(
            "表情包习惯沉淀",
            "统计群友发送的图片表情，跨过次数阈值后把「常用表情包」写进该群友的人物事实",
            "只统计图片消息；QQ 商城表情（mface）暂不计入",
        ),
    )
    llm_sticker_habit_min_count: int = Field(
        default=5,
        ge=1,
        le=1000,
        description=field_help(
            "表情包习惯最少发送次数",
            "同一群友发同一张图达到该次数才沉淀为习惯事实；计数受图片采集限流影响，是下界",
        ),
    )
    llm_sticker_habit_top_k: int = Field(
        default=1,
        ge=1,
        le=3,
        description=field_help(
            "表情包习惯事实条数",
            "每位群友最多沉淀几张最爱表情包；调小后多余的条目会在下轮扫描时自动清理",
        ),
    )
    llm_sticker_habit_backfill_days: int = Field(
        default=7,
        ge=0,
        le=90,
        description=field_help(
            "表情包习惯回填天数",
            "首次扫描从多少天前的消息开始统计；0 表示只从启动后开始",
            "仅影响新群的初始游标，改大不会重扫已有游标的群",
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
    llm_memory_rag_enabled: bool = Field(
        default=True,
        description=field_help(
            "群里「记住：…」以及相关记忆，要不要检索后塞进对话",
            "开=可写入并按相关度注入（推荐）；关=不走群记忆检索，牛牛更「健忘」",
            "关闭后下方记忆条数、自动沉淀等细项基本不再参与对话注入",
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
    llm_embedding_provider: EmbeddingProviderChoice = Field(
        default="",
        description=field_help(
            "向量提供方",
            "远程=用 OpenAI 兼容 /embeddings（需配置下方 Embedding 线路）；"
            "本机=进程内 fastembed；占位=不做真实语义；自动=模型名非 stub 则远程，否则占位",
            "仅「远程」或自动且模型非 stub 时需要配 Embedding 线路",
        ),
    )
    llm_embedding_provider_id: str = Field(
        default="",
        description=field_help(
            "Embedding 线路",
            "点「添加网关」从名册选 Provider，或手填向量服务地址与模型（如 text-embedding-3-small）",
            "仅向量提供方为远程时使用；未配则回落对话主线",
        ),
        json_schema_extra=ui_provider_gateway(
            mode="split",
            allow_manual=True,
            primary={
                "provider_id": "llm_embedding_provider_id",
                "base_url": "llm_embedding_base_url",
                "api_key": "llm_embedding_api_key",
                "model": "llm_embedding_model",
            },
            backends="llm_embedding_api_backends",
            title="Embedding 线路",
            subtitle="从名册选 Provider 或手填地址；模型名写在线路里。",
            label="Embedding 线路",
            group="记忆",
        ),
    )
    llm_embedding_model: str = Field(
        default="stub",
        description=field_help(
            "Embedding 模型名",
            "远程时填服务商模型名（如 text-embedding-3-small）；若仍写 stub，远程会默认 text-embedding-3-small。"
            "本机可留 stub（默认 BAAI/bge-small-zh-v1.5）",
            "换模型后旧向量可能对不上，需重新生成或等后台回填",
        ),
    )
    llm_embedding_base_url: str = Field(
        default="",
        description=field_help(
            "Embedding 接口地址（可选）",
            "留空=用线路所选 Provider 或对话主线。向量服务与聊天不是同一套时再手填",
            "只填根地址即可，不要带 /embeddings",
        ),
    )
    llm_embedding_api_key: str = Field(
        default="",
        description=field_help(
            "Embedding API Key（可选）",
            "留空=用线路 Provider 或对话主线密钥。仅当向量服务要用另一套 Key 时填写",
            "敏感项，保存后以落盘为准",
        ),
        json_schema_extra={"secret": True},
    )
    llm_embedding_api_backends: list[dict] = Field(
        default_factory=list,
        description=field_help(
            "Embedding 备线",
            "主线路失败时的备用网关列表（JSON）；一般由 Embedding 线路面板维护，无需手改",
            "条目含 provider_id，或 base_url+api_key，可选 model",
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
        default=False,
        description=field_help(
            "是否保留逐条启发式沉淀（默认关，推荐用摘要沉淀代替）",
            "开=每句话都可能直接写入群记忆（旧行为，易记入寒暄/碎片）；关=只靠摘要或人工「记住：」",
            "建议保持关闭；真正的群事件交给下方的「多人共同事件自动摘要」",
        ),
    )
    llm_memory_auto_episode_summary_enabled: bool = Field(
        default=True,
        description=field_help(
            "要不要把多人讨论过的共同事件自动摘要成群记忆",
            "开=成功回复后异步摘要近期多人对话（推荐）；关=仅保留现有启发式自动沉淀",
            "只处理至少两人参与、至少三条群友消息的窗口；模型失败时不会影响正常聊天",
        ),
    )
    llm_memory_auto_episode_cooldown_sec: int = Field(
        default=600,
        ge=0,
        le=3600,
        description=field_help(
            "同一会话两次自动沉淀记忆至少隔多少秒",
            "默认 600（10 分钟）。想少记一点调大；0=不冷却（可能记太勤）。须开启自动沉淀",
            "过密写入会产生大量相似记忆，检索变吵",
        ),
    )
    llm_memory_auto_episode_daily_budget: int = Field(
        default=30,
        ge=0,
        le=100000,
        description=field_help(
            "每天最多做几次「多人共同事件」自动摘要",
            "默认 30。想控制模型费用调低（如 10）；0=不限制",
            "摘要会额外调用一次模型；此预算用于防止高频群聊把费用刷爆",
        ),
    )
    llm_memory_auto_ip_enabled: bool = Field(
        default=False,
        description=field_help(
            "要不要自动从群聊提炼 IP 知识（游戏/番剧设定等）",
            "开=群聊讨论到任何作品时，由模型自动判定并提炼稳定设定写入记忆（推荐）",
            "会额外调用模型；每群 30 分钟冷却 + 每日预算上限",
        ),
    )
    llm_memory_auto_ip_daily_budget: int = Field(
        default=100,
        ge=0,
        le=100000,
        description=field_help(
            "每天最多提炼几次 IP 知识",
            "默认 100。想控制模型费用调低（如 50）；0=不限制",
            "须开启「自动提炼 IP 知识」",
        ),
    )
    llm_memory_auto_ip_cooldown_sec: int = Field(
        default=1800,
        ge=0,
        le=86400,
        description=field_help(
            "同一群两次提炼 IP 知识至少隔多少秒",
            "默认 1800（30 分钟）。想更频繁调低；0=不冷却",
            "过密提炼会产生重复知识",
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
    llm_memory_decay_half_life_days: float = Field(
        default=30.0,
        ge=0.0,
        le=3650.0,
        description=field_help(
            "低重要性记忆多久淡出一半（半衰期，天）",
            "默认 30 天。想记更久调大（如 90）；想更轻快忘掉调小",
            "重要性低于「淡出下限」的记忆按此半衰期衰减；0=不衰减",
        ),
    )
    llm_memory_decay_min_importance: float = Field(
        default=0.6,
        ge=0.0,
        le=1.0,
        description=field_help(
            "低于此重要性评分的记忆才开始随时间淡出",
            "默认 0.6。调高=更多低分记忆会被淡出；调低=只让极低分记忆淡出",
            "仅影响低于此分的记忆；高分记忆长期保留",
        ),
    )
    llm_memory_hit_boost_enabled: bool = Field(
        default=True,
        description=field_help(
            "近期被检索命中的记忆要不要临时提高权重",
            "开=刚被用到的记忆短期内更可能再次被想起（推荐）；关=不做命中加权",
            "帮助在对话中连续引用刚聊过的话题",
        ),
    )
    llm_memory_hit_boost_sec: int = Field(
        default=3600,
        ge=0,
        le=2592000,
        description=field_help(
            "命中加权的有效期（秒）",
            "默认 3600（1 小时）。想更短暂调小；0=不设有效期",
            "须开启「命中加权」",
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
    llm_relationship_affinity_enabled: bool = Field(
        default=True,
        description=field_help(
            "要不要记录每位群友对牛牛的好感度",
            "开=被@、点名或追问时按语气调整好感，对话更有人情味（推荐）；关=不做好感度记录",
            "好感度会显示在对话的关系备注里，并影响牛牛对低好感者是否接话",
        ),
    )
    llm_relationship_affinity_ambient_enabled: bool = Field(
        default=True,
        description=field_help(
            "普通群聊时也做轻量好感度观察",
            "开=群里没@牛牛时，牛牛也会悄悄留意亲昵/冲话，用规则词表微调好感（不调大模型，省费用）；关=只有被@、点名、追问才更新好感度",
            "只按词表小步调整，不会误判反讽，也不会因为普通闲聊突然掉好感",
        ),
    )
    llm_relationship_affinity_delta_max: float = Field(
        default=0.20,
        ge=0.0,
        le=1.0,
        description=field_help(
            "单次好感度变动的最大幅度",
            "默认 0.20。越大，一两句话就能明显拉近/拉远关系；越小越平滑",
            "好感度本身在 -1 到 +1 之间",
        ),
    )
    llm_relationship_affinity_llm_cooldown_s: int = Field(
        default=24,
        ge=0,
        le=86400,
        description=field_help(
            "规则词表判不出好感时，交给大模型判定的最小间隔（秒）",
            "默认 24。太小会频繁调大模型；越大越省调用，但反应会变慢",
            "只有规则命中不了的话才走大模型",
        ),
    )
    llm_relationship_affinity_llm_daily_limit: int = Field(
        default=1000,
        ge=0,
        le=100000,
        description=field_help(
            "每天最多让大模型判定几次好感度",
            "默认 1000。防止规则判不出时无上限调用大模型产生费用；0=不限制",
            "与冷却间隔共同约束；超出后当天不再用大模型判定",
        ),
    )
    llm_relationship_affinity_daily_decay_step: float = Field(
        default=0.005,
        ge=0.0,
        le=1.0,
        description=field_help(
            "好感度每天向中立回落的幅度",
            "默认 0.005，让冷淡/热情随时间慢慢淡出；0=不回落后只升不降",
            "若想手动纠偏，可在关系档案里直接改好感度",
        ),
    )
    llm_relationship_affinity_silence_threshold: float = Field(
        default=-0.45,
        ge=-1.0,
        le=0.0,
        description=field_help(
            "好感度低于多少时，牛牛对非点名发言开始爱搭不理",
            "默认 -0.45。只有低到这条线以下，牛牛才会更少接对方的闲聊",
            "被@、点名、追问仍会正常回复",
        ),
    )
    llm_relationship_affinity_silence_max_penalty: int = Field(
        default=40,
        ge=0,
        le=200,
        description=field_help(
            "好感度极低时，接话积极性的最多扣分",
            "默认 40。越大，对低好感者越沉默；0=好感度不影响接话",
            "配合上方的静默阈值使用",
        ),
    )


def get_llm_webui_config() -> LlmWebuiConfig:
    from pallas.core.foundation.config.repo_settings import repo_env_raw_value
    from pallas.product.llm.config import resolve_chat_tts_enabled, resolve_legacy_rwkv_drunk_chat_enabled

    cfg = get_llm_config()
    return LlmWebuiConfig(
        ai_server_host=cfg.ai_server_host,
        ai_server_port=cfg.ai_server_port,
        llm_chat_enabled=cfg.llm_chat_enabled,
        chat_enable=resolve_legacy_rwkv_drunk_chat_enabled(),
        chat_tts_enable=resolve_chat_tts_enabled(),
        drunk_tts_min_drunkenness=cfg.drunk_tts_min_drunkenness,
        drunk_tts_min_chars=cfg.drunk_tts_min_chars,
        llm_governance_enabled=cfg.llm_governance_enabled,
        llm_session_enabled=cfg.llm_session_enabled,
        llm_session_user_window=cfg.llm_session_user_window,
        llm_session_user_storage_window=cfg.llm_session_user_storage_window,
        llm_session_group_window=cfg.llm_session_group_window,
        llm_session_group_ambient_enabled=cfg.llm_session_group_ambient_enabled,
        llm_session_user_ttl_sec=cfg.llm_session_user_ttl_sec,
        llm_session_private_ttl_sec=cfg.llm_session_private_ttl_sec,
        llm_session_max_content_len=cfg.llm_session_max_content_len,
        llm_session_strip_vision_enabled=cfg.llm_session_strip_vision_enabled,
        llm_session_summary_enabled=cfg.llm_session_summary_enabled,
        llm_session_summary_threshold=cfg.llm_session_summary_threshold,
        llm_session_summary_keep_messages=cfg.llm_session_summary_keep_messages,
        llm_session_summary_cooldown_sec=cfg.llm_session_summary_cooldown_sec,
        llm_speak_perception_enabled=cfg.llm_speak_perception_enabled,
        llm_speak_mention_enabled=cfg.llm_speak_mention_enabled,
        llm_speak_ambient_enabled=cfg.llm_speak_ambient_enabled,
        llm_speak_ambient_rate=cfg.llm_speak_ambient_rate,
        llm_speak_ambient_min_score=cfg.llm_speak_ambient_min_score,
        llm_speak_ambient_cooldown_sec=cfg.llm_speak_ambient_cooldown_sec,
        llm_speak_ambient_budget_limit=cfg.llm_speak_ambient_budget_limit,
        llm_speak_ambient_budget_window_sec=cfg.llm_speak_ambient_budget_window_sec,
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
        mcp_servers=list(cfg.mcp_servers or []),
        llm_mcp_http_allowlist=str(repo_env_raw_value("LLM_MCP_HTTP_ALLOWLIST") or "").strip(),
        web_search_api_url=str(repo_env_raw_value("WEB_SEARCH_API_URL") or "").strip(),
        tavily_api_key=str(repo_env_raw_value("TAVILY_API_KEY") or "").strip(),
        llm_chat_max_concurrency=cfg.llm_chat_max_concurrency,
        llm_repeater_feedback_enabled=cfg.llm_repeater_feedback_enabled,
        llm_repeater_bias_enabled=cfg.llm_repeater_bias_enabled,
        conversation_feature_level=cfg.conversation_feature_level or "",  # type: ignore[arg-type]
        llm_reply_gate_enabled=cfg.llm_reply_gate_enabled,
        llm_current_turn_decision_enabled=cfg.llm_current_turn_decision_enabled,
        llm_shut_up_silence_enabled=cfg.llm_shut_up_silence_enabled,
        llm_shut_up_silence_min_sec=cfg.llm_shut_up_silence_min_sec,
        llm_shut_up_silence_max_sec=cfg.llm_shut_up_silence_max_sec,
        llm_chat_queue_merge=cfg.llm_chat_queue_merge,
        llm_chat_queue_enabled=cfg.llm_chat_queue_enabled,
        llm_chat_queue_max=cfg.llm_chat_queue_max,
        llm_chat_queue_wait_sec=cfg.llm_chat_queue_wait_sec,
        llm_output_filter_enabled=cfg.llm_output_filter_enabled,
        llm_output_filter_chat_hard_phrases=cfg.llm_output_filter_chat_hard_phrases,
        llm_output_filter_chat_soft_phrases=cfg.llm_output_filter_chat_soft_phrases,
        llm_persona_output_firewall=cfg.llm_persona_output_firewall,
        llm_reply_postprocess_enabled=cfg.llm_reply_postprocess_enabled,
        llm_reply_trim_terminal_period_enabled=cfg.llm_reply_trim_terminal_period_enabled,
        llm_reply_trim_terminal_period_rate=cfg.llm_reply_trim_terminal_period_rate,
        llm_reply_split_randomize_enabled=cfg.llm_reply_split_randomize_enabled,
        llm_reply_split_randomize_keep_rate=cfg.llm_reply_split_randomize_keep_rate,
        llm_bubble_delay_base_sec=cfg.llm_bubble_delay_base_sec,
        llm_bubble_delay_per_char=cfg.llm_bubble_delay_per_char,
        llm_bubble_delay_jitter=cfg.llm_bubble_delay_jitter,
        llm_reply_mention_cooldown_sec=cfg.llm_reply_mention_cooldown_sec,
        llm_reply_typo_enabled=cfg.llm_reply_typo_enabled,
        llm_reply_typo_rate=cfg.llm_reply_typo_rate,
        llm_sticker_fit_enabled=cfg.llm_sticker_fit_enabled,
        llm_chat_sticker_enabled=cfg.llm_chat_sticker_enabled,
        llm_chat_sticker_cooldown_sec=cfg.llm_chat_sticker_cooldown_sec,
        llm_chat_sticker_max_per_hour=cfg.llm_chat_sticker_max_per_hour,
        llm_sticker_vision_enabled=cfg.llm_sticker_vision_enabled,
        llm_sticker_vision_candidate_count=cfg.llm_sticker_vision_candidate_count,
        llm_sticker_vision_timeout_sec=cfg.llm_sticker_vision_timeout_sec,
        llm_sticker_vision_max_per_hour=cfg.llm_sticker_vision_max_per_hour,
        llm_sticker_label_backfill_enabled=cfg.llm_sticker_label_backfill_enabled,
        llm_sticker_label_backfill_daily_limit=cfg.llm_sticker_label_backfill_daily_limit,
        llm_sticker_label_realtime_daily_limit=cfg.llm_sticker_label_realtime_daily_limit,
        llm_semantic_style_realtime_daily_limit=cfg.llm_semantic_style_realtime_daily_limit,
        llm_sticker_habit_enabled=cfg.llm_sticker_habit_enabled,
        llm_sticker_habit_min_count=cfg.llm_sticker_habit_min_count,
        llm_sticker_habit_top_k=cfg.llm_sticker_habit_top_k,
        llm_sticker_habit_backfill_days=cfg.llm_sticker_habit_backfill_days,
        llm_reply_effect_eval_enabled=cfg.llm_reply_effect_eval_enabled,
        llm_memory_rag_enabled=cfg.llm_memory_rag_enabled,
        llm_vector_retrieve=cfg.llm_vector_retrieve,
        llm_embedding_model=cfg.llm_embedding_model,
        llm_embedding_provider=_embedding_provider_choice(cfg.llm_embedding_provider),
        llm_embedding_provider_id=str(getattr(cfg, "llm_embedding_provider_id", "") or ""),
        llm_embedding_base_url=str(getattr(cfg, "llm_embedding_base_url", "") or ""),
        llm_embedding_api_key=str(getattr(cfg, "llm_embedding_api_key", "") or ""),
        llm_embedding_api_backends=list(getattr(cfg, "llm_embedding_api_backends", None) or []),
        llm_memory_rag_top_k=cfg.llm_memory_rag_top_k,
        llm_memory_max_per_group=cfg.llm_memory_max_per_group,
        llm_memory_content_max_len=cfg.llm_memory_content_max_len,
        llm_memory_auto_episode_enabled=cfg.llm_memory_auto_episode_enabled,
        llm_memory_auto_episode_summary_enabled=cfg.llm_memory_auto_episode_summary_enabled,
        llm_memory_auto_episode_cooldown_sec=cfg.llm_memory_auto_episode_cooldown_sec,
        llm_memory_auto_episode_daily_budget=cfg.llm_memory_auto_episode_daily_budget,
        llm_memory_auto_ip_enabled=cfg.llm_memory_auto_ip_enabled,
        llm_memory_auto_ip_daily_budget=cfg.llm_memory_auto_ip_daily_budget,
        llm_memory_auto_ip_cooldown_sec=cfg.llm_memory_auto_ip_cooldown_sec,
        llm_memory_graph_extract_enabled=cfg.llm_memory_graph_extract_enabled,
        llm_memory_graph_extract_on_write=cfg.llm_memory_graph_extract_on_write,
        llm_memory_hiergraph_max_layers=cfg.llm_memory_hiergraph_max_layers,
        llm_memory_decay_half_life_days=cfg.llm_memory_decay_half_life_days,
        llm_memory_decay_min_importance=cfg.llm_memory_decay_min_importance,
        llm_memory_hit_boost_enabled=cfg.llm_memory_hit_boost_enabled,
        llm_memory_hit_boost_sec=cfg.llm_memory_hit_boost_sec,
        llm_relationship_notes_enabled=cfg.llm_relationship_notes_enabled,
        llm_relationship_affinity_enabled=cfg.llm_relationship_affinity_enabled,
        llm_relationship_affinity_ambient_enabled=cfg.llm_relationship_affinity_ambient_enabled,
        llm_relationship_affinity_delta_max=cfg.llm_relationship_affinity_delta_max,
        llm_relationship_affinity_llm_cooldown_s=cfg.llm_relationship_affinity_llm_cooldown_s,
        llm_relationship_affinity_llm_daily_limit=cfg.llm_relationship_affinity_llm_daily_limit,
        llm_relationship_affinity_daily_decay_step=cfg.llm_relationship_affinity_daily_decay_step,
        llm_relationship_affinity_silence_threshold=cfg.llm_relationship_affinity_silence_threshold,
        llm_relationship_affinity_silence_max_penalty=cfg.llm_relationship_affinity_silence_max_penalty,
    )
