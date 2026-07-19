from pydantic import BaseModel, Field

from pallas.console.webui import install_hot_reload_config
from pallas.console.webui.field_help import field_help

FIELD_TO_ENV: dict[str, str] = {
    "learn_concurrency": "PALLAS_REPEATER_LEARN_CONCURRENCY",
    "learn_queue_max_size": "PALLAS_REPEATER_LEARN_QUEUE_SIZE",
    "fanout_enabled": "PALLAS_REPEATER_FANOUT_ENABLED",
    "fanout_max_bots": "PALLAS_REPEATER_FANOUT_MAX_BOTS",
}


class Config(BaseModel, extra="ignore"):
    answer_threshold: int = Field(
        default=3,
        description="「接话」随机阈值基数；数值越大 Bot 越少插话，越小则更爱接话。",
    )
    answer_threshold_weights: list[int] = Field(
        default=[7, 23, 70],
        description="与接话阈值配合的三段权重（JSON 数组），影响不同档位的接话倾向。",
    )
    topics_size: int = Field(
        default=16,
        description="每个群记住的上下文关键词条数上限，用于联想回复。",
    )
    topics_importance: int = Field(
        default=10000,
        description="命中上下文关键词时对接话权重的额外加成。",
    )
    cross_group_threshold: int = Field(
        default=2,
        description="至少多少个群出现相同短句后，才将其提升为全局可复用语料。",
    )
    repeat_threshold: int = Field(
        default=3,
        description="群内连续相同发言达到该次数时触发复读。",
    )
    repeat_ignore_user_ids: list[int] = Field(
        default_factory=list,
        description="复读判定与学习时忽略的第三方 QQ 号列表。",
    )
    speak_threshold: int = Field(
        default=5,
        description="主动发言的随机阈值；数值越小 Bot 越常主动说话。",
    )
    duplicate_reply: int = Field(
        default=10,
        description="同一条已发送回复在后续多少轮内不再重复选用。",
    )
    split_probability: float = Field(
        default=0.5,
        description="按逗号把一条回复拆成多条发送的概率。",
    )
    drunk_tts_threshold: int = Field(
        default=6,
        description="醉酒状态下，正文超过多少字时改为发语音（TTS）。",
    )
    speak_continuously_probability: float = Field(
        default=0.5,
        description="主动发言后，继续连说下一句的概率。",
    )
    speak_poke_probability: float = Field(
        default=0.6,
        description="主动发言时附带随机戳一戳群友的概率。",
    )
    speak_continuously_max_len: int = Field(
        default=2,
        description="连续主动发言最多连续几句。",
    )
    save_time_threshold: int = Field(
        default=3600,
        description="距上次持久化至少间隔多少秒再写盘（与条数条件为「或」关系）。",
    )
    save_count_threshold: int = Field(
        default=1000,
        description="单群聊天记录在内存中超过多少条触发持久化。",
    )
    save_reserved_size: int = Field(
        default=100,
        description="持久化后每个群在内存中保留的最近消息条数。",
    )
    learn_concurrency: int = Field(
        default=8,
        ge=1,
        le=128,
        description=field_help(
            "后台同时学多少条群消息语料",
            "机器性能好可适当加大；在「复读 → 插件配置」也可改",
        ),
    )
    learn_queue_max_size: int = Field(
        default=2048,
        ge=64,
        le=20000,
        description=field_help(
            "等待学习的消息最多排多少条",
            "队列满时只跳过学习，不影响复读和口令回复",
        ),
    )
    fanout_enabled: bool = Field(
        default=False,
        description=field_help(
            "同群有多只牛时，是否让多只牛一起接话",
            "分片或多牛部署可开；单牛单进程保持关闭",
        ),
    )
    fanout_max_bots: int = Field(
        default=0,
        ge=0,
        le=64,
        description=field_help(
            "同群接话时最多几只牛一起响应",
            "填 0 表示不限制；仅在开启「多只牛一起接话」时有效",
        ),
    )
    enable_reaction: bool = Field(default=True, description="是否启用 QQ 表情回应（Reaction）能力。")
    enable_probability_reaction: bool = Field(
        default=True,
        description="日常消息是否按概率随机触发表情回应。",
    )
    reaction_probability: float = Field(
        default=0.1,
        description="日常消息触发表情回应的概率（0~1）。",
    )
    enable_face_reaction: bool = Field(
        default=False,
        description="收到带「QQ 小黄脸」表情的消息时是否自动回应。",
    )
    enable_auto_reply_on_reaction: bool = Field(
        default=True,
        description="他人对任意消息发表情回应时，Bot 是否跟着回应。",
    )
    reply_with_same_emoji: bool = Field(
        default=True,
        description="跟表情回应时是否优先使用与对方相同的表情。",
    )


def sync_repeater_runtime_constants(cfg: Config) -> None:
    from . import emoji_reaction as emoji_mod
    from . import model as model_mod
    from . import responder as resp_mod

    for mod in (model_mod, resp_mod, emoji_mod):
        mod.plugin_config = cfg

    choice = list(range(cfg.answer_threshold - len(cfg.answer_threshold_weights) + 1, cfg.answer_threshold + 1))
    chat_attrs = {
        "ANSWER_THRESHOLD": cfg.answer_threshold,
        "ANSWER_THRESHOLD_WEIGHTS": cfg.answer_threshold_weights,
        "TOPICS_SIZE": cfg.topics_size,
        "TOPICS_IMPORTANCE": cfg.topics_importance,
        "CROSS_GROUP_THRESHOLD": cfg.cross_group_threshold,
        "REPEAT_THRESHOLD": cfg.repeat_threshold,
        "SPEAK_THRESHOLD": cfg.speak_threshold,
        "DUPLICATE_REPLY": cfg.duplicate_reply,
        "SPLIT_PROBABILITY": cfg.split_probability,
        "DRUNK_TTS_THRESHOLD": cfg.drunk_tts_threshold,
        "SPEAK_CONTINUOUSLY_PROBABILITY": cfg.speak_continuously_probability,
        "SPEAK_POKE_PROBABILITY": cfg.speak_poke_probability,
        "SPEAK_CONTINUOUSLY_MAX_LEN": cfg.speak_continuously_max_len,
        "SAVE_TIME_THRESHOLD": cfg.save_time_threshold,
        "SAVE_COUNT_THRESHOLD": cfg.save_count_threshold,
        "SAVE_RESERVED_SIZE": cfg.save_reserved_size,
        "ANSWER_THRESHOLD_CHOICE_LIST": choice,
    }
    responder_attrs = {
        "ANSWER_THRESHOLD": cfg.answer_threshold,
        "ANSWER_THRESHOLD_WEIGHTS": cfg.answer_threshold_weights,
        "TOPICS_SIZE": cfg.topics_size,
        "TOPICS_IMPORTANCE": cfg.topics_importance,
        "CROSS_GROUP_THRESHOLD": cfg.cross_group_threshold,
        "REPEAT_THRESHOLD": cfg.repeat_threshold,
        "DUPLICATE_REPLY": cfg.duplicate_reply,
        "SPLIT_PROBABILITY": cfg.split_probability,
        "SAVE_RESERVED_SIZE": cfg.save_reserved_size,
        "ANSWER_THRESHOLD_CHOICE_LIST": choice,
    }
    for name, value in chat_attrs.items():
        setattr(model_mod.Chat, name, value)
    for name, value in responder_attrs.items():
        setattr(resp_mod.Responder, name, value)


def on_repeater_config_reload(cfg: Config) -> None:
    sync_repeater_runtime_constants(cfg)
    from .learn_runtime_config import clear_repeater_learn_runtime_config_cache

    clear_repeater_learn_runtime_config_cache()


plugin_webui = install_hot_reload_config(
    Config,
    config_module=__name__,
    field_to_env=FIELD_TO_ENV,
    on_reload=on_repeater_config_reload,
)
get_repeater_config = plugin_webui.get
reload_repeater_config = plugin_webui.reload
clear_repeater_config_cache = plugin_webui.clear_cache
