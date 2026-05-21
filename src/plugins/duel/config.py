from __future__ import annotations

import os
from threading import Lock
from typing import Any, Self

from nonebot import get_plugin_config
from pydantic import BaseModel, Field, model_validator

from src.common.config.dotenv import merged_repo_dotenv_upper, repo_layered_dotenv_files_exist
from src.common.webui.registry import PluginWebuiConfigHooks, register_plugin_webui_config


class Config(BaseModel, extra="ignore"):
    """决斗插件配置（WebUI 插件配置页可读写，写入 .env 大写键名）。"""

    # —— 胜负惩罚 ——
    duel_penalty_minutes: int = Field(
        default=10,
        ge=1,
        le=1440,
        description="败者惩罚时长（分钟）：群名片与消息规则，期满自动恢复原名片。",
    )
    duel_penalty_loser_card: str = Field(
        default="THE LOSER",
        min_length=1,
        max_length=60,
        description="败者群名片（双牛局与人类局败者；人类局须本牛为群管）。",
    )
    duel_penalty_winner_card: str = Field(
        default="TRUE PALLAS",
        min_length=1,
        max_length=60,
        description="胜者群名片（仅双牛对决的胜方牛）。",
    )
    duel_penalty_bot_fake_msg: str = Field(
        default="唔....我是假的牛牛，不应与你说话...",
        min_length=1,
        max_length=200,
        description="双牛对决败者牛随后续发言被替换的文案。",
    )
    duel_penalty_bot_sad_msg: str = Field(
        default="牛牛输地很伤心，看起来决定不再讲话了...",
        min_length=1,
        max_length=200,
        description="人类局中败者牛随后续发言被替换的文案。",
    )
    duel_penalty_human_noise_msg: str = Field(
        default="有一点噪音产生了..",
        min_length=1,
        max_length=200,
        description="人类局败者惩罚开始时由处理决斗的牛在群内代发一次的文案（不撤回消息）。",
    )

    # —— 流程与节奏 ——
    duel_bot_cooldown_sec: int = Field(
        default=5,
        ge=0,
        le=300,
        description="同一群内两次「牛牛决斗/八角笼」类指令的最短间隔（秒），防多 Bot 抢答。",
    )
    duel_round_pause_min_sec: float = Field(
        default=10.0,
        ge=0.0,
        le=600.0,
        description="第 2 幕起幕间最短停顿（秒）；与最大值相同则固定间隔。第 1 幕开演后无等待。",
    )
    duel_round_pause_max_sec: float = Field(
        default=15.0,
        ge=0.0,
        le=600.0,
        description="第 2 幕起幕间最长停顿（秒），须不小于最短；二者相等即为固定秒数。",
    )
    duel_compact_round: bool = Field(
        default=True,
        description="紧凑发群：幕内剧目合并、QTE 与上文同条提示、结算写入幕末；段末不重复 HP/DP 变动行。",
    )
    duel_total_rounds: int = Field(
        default=5,
        ge=1,
        le=20,
        description="单场决斗默认总幕数（指令未写 X幕/X回合 时使用）。",
    )
    duel_player_rounds_max: int = Field(
        default=20,
        ge=1,
        le=20,
        description="玩家指令「牛牛决斗 … N幕」可指定的幕数上限。",
    )

    # —— 事件与 QTE 权重 ——
    duel_public_round_weight: float = Field(
        default=0.32,
        ge=0.0,
        le=1.0,
        description="每一幕抽中「泰拉节庆」公共场的概率；0 表示几乎不抽公共幕。",
    )
    duel_public_terra_weight_mult: float = Field(
        default=1.5,
        ge=0.1,
        le=10.0,
        description="歌咏场内泰拉公共事件（非乱入）权重倍率，相对 JSON weight 再抬高。",
    )
    duel_operator_intrusion_chance: float = Field(
        default=0.1,
        ge=0.0,
        le=1.0,
        description="进入歌咏场后，本幕改为干员乱入的概率（与泰拉公共互斥分支）。",
    )
    duel_intrusion_pallas_roll_chance: float = Field(
        default=0.06,
        ge=0.0,
        le=1.0,
        description="乱入事件 public_ark_intrusion 中，随机抽中帕拉斯而非其他干员的概率。",
    )
    duel_qte_event_weight_mult: float = Field(
        default=1.6,
        ge=0.1,
        le=10.0,
        description="交锋/兵刃等池中「关键词 QTE」事件的权重倍率（不含歌咏乱入）。",
    )
    duel_exchange_qte_chance: float = Field(
        default=0.32,
        ge=0.0,
        le=1.0,
        description="兵刃对击幕在无内置 QTE 时，额外触发关键词 QTE 的概率。",
    )
    duel_exchange_qte_race_chance: float = Field(
        default=0.38,
        ge=0.0,
        le=1.0,
        description="兵刃随机 QTE 中，生成双方抢攻（对对手造成伤害）而非受创方拆招的概率。",
    )
    duel_intrusion_race_chance: float = Field(
        default=0.45,
        ge=0.0,
        le=1.0,
        description="干员乱入 QTE 中，双方抢先咏名（抢认）而非仅 target 指定单方应答的概率。",
    )

    # —— 泰拉干员资源（resource/arknights） ——
    duel_auto_sync_operators: bool = Field(
        default=True,
        description="缺 operators_6star.json 时启动自动拉取干员表（与 scripts/fetch_arknights_duel_data.py 同源）。",
    )
    duel_avatar_download_on_use: bool = Field(
        default=True,
        description="乱入发图仅走本地 PNG；缺文件时按需从上游拉一张到 resource（不用远程 URL 发群）。",
    )
    duel_avatar_download_on_startup: bool = Field(
        default=False,
        description="启动时批量补全缺失头像（约百张，耗时长；建议用脚本预拉或仅开按需下载）。",
    )

    # —— 牛自动咏名/拆招 ——
    duel_bot_qte_intrusion_success_rate: float = Field(
        default=0.68,
        ge=0.0,
        le=1.0,
        description="应答方为牛时，干员唤名（咏名）QTE 自动答对概率。",
    )
    duel_bot_qte_keyword_success_rate: float = Field(
        default=0.74,
        ge=0.0,
        le=1.0,
        description="应答方为牛时，关键词拆招 QTE 自动答对概率。",
    )
    duel_bot_qte_fail_speak_wrong_chance: float = Field(
        default=0.72,
        ge=0.0,
        le=1.0,
        description="自动 QTE 失败时，仍发出错误答案（嘴瓢）的概率。",
    )
    duel_bot_qte_fail_silent_chance: float = Field(
        default=0.18,
        ge=0.0,
        le=1.0,
        description="自动 QTE 失败时，完全不发言的概率。",
    )

    @model_validator(mode="after")
    def duel_round_pause_order(self) -> Self:
        if self.duel_round_pause_max_sec < self.duel_round_pause_min_sec:
            msg = "duel_round_pause_max_sec must be >= duel_round_pause_min_sec"
            raise ValueError(msg)
        return self

    @classmethod
    def from_env(cls) -> Self:
        merged = merged_repo_dotenv_upper()
        data: dict[str, Any] = {}
        for name, field in cls.model_fields.items():
            key = name.upper()
            raw: str | None = None
            if key in os.environ:
                raw = os.environ.get(key)
            elif key in merged:
                raw = merged[key]
            if raw is None:
                continue
            text = str(raw).strip()
            ann_text = str(field.annotation).lower()
            if "float" in ann_text:
                data[name] = float(text)
            elif "int" in ann_text:
                data[name] = int(text)
            else:
                data[name] = text
        return cls.model_validate(data)


_config_lock = Lock()
_cached_duel_config: Config | None = None


def clear_duel_config_cache() -> None:
    global _cached_duel_config
    with _config_lock:
        _cached_duel_config = None


def get_duel_config() -> Config:
    global _cached_duel_config
    with _config_lock:
        if _cached_duel_config is None:
            if repo_layered_dotenv_files_exist():
                _cached_duel_config = Config.from_env()
            else:
                _cached_duel_config = get_plugin_config(Config)
        return _cached_duel_config


def reload_duel_plugin_config() -> Config:
    """WebUI 写入 .env 后调用，使惩罚/权重/幕间停顿等立即生效（不重载 JSON 剧目）。"""
    clear_duel_config_cache()
    return get_duel_config()


class _DuelConfigProxy:
    """兼容 ``plugin_config.xxx`` 写法，每次访问读取最新缓存。"""

    def __getattr__(self, name: str) -> Any:
        return getattr(get_duel_config(), name)


plugin_config = _DuelConfigProxy()

_duel_webui_hooks = PluginWebuiConfigHooks(
    get=get_duel_config,
    reload=reload_duel_plugin_config,
    clear_cache=clear_duel_config_cache,
)
register_plugin_webui_config(__name__, _duel_webui_hooks)
register_plugin_webui_config("src.plugins.duel", _duel_webui_hooks)
