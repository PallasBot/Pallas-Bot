from typing import Self

from pydantic import BaseModel, Field, model_validator

from src.common.webui import install_hot_reload_config, plugin_config_proxy


class Config(BaseModel, extra="ignore"):
    dream_drift_queue_tick_probability: float = Field(
        default=0.8,
        ge=0.0,
        le=1.0,
        description="每轮 worker 从「他群刚漂流过来」的队列取内容的概率；调高更常发实时漂流，调低更依赖历史与已学句。",
    )
    dream_archive_image_probability: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="本轮允许发图时，从「牛牛画画」归档里抽一张图尝试展示的概率。",
    )
    dream_echo_resample_attempts: int = Field(
        default=22,
        ge=1,
        le=48,
        description="从复读已学句抽样时的最大重试次数，越大越容易换到一条可发送的短句。",
    )
    dream_prefer_learned_echo_probability: float = Field(
        default=0.2,
        ge=0.0,
        le=1.0,
        description="在未发漂流内容后，优先尝试「已学句」而非历史梦话的概率；0 表示固定先历史再已学句。",
    )
    dream_hist_resample_attempts: int = Field(
        default=12,
        ge=1,
        le=48,
        description="从历史梦话抽样时的最大重试次数。",
    )
    dream_worker_sleep_min_sec: float = Field(
        default=15.0,
        ge=5.0,
        le=1200.0,
        description="本群未醉酒时，每轮梦话发送后的最短休眠秒数（与最大值之间随机）。",
    )
    dream_worker_sleep_max_sec: float = Field(
        default=135.0,
        ge=5.0,
        le=1200.0,
        description="每轮梦话后的最长休眠秒数，须不小于最小休眠。",
    )
    dream_message_retention_days: int = Field(
        default=90,
        ge=7,
        le=3650,
        description="历史梦话抽样时只考虑最近多少天内的记录；越大语料池越深、库越大。",
    )
    dream_history_recent_dedupe_max: int = Field(
        default=120,
        ge=0,
        le=4000,
        description="按群记录最近已发梦话的去重键数量，减轻短期重复；0 表示不做历史去重。",
    )
    dream_history_recency_power: float = Field(
        default=2.25,
        ge=0.0,
        le=8.0,
        description="历史抽样时偏向新记录的强度；0 为均匀随机，越大越不爱抽到旧句。",
    )

    @model_validator(mode="after")
    def dream_worker_sleep_order(self) -> Self:
        if self.dream_worker_sleep_max_sec < self.dream_worker_sleep_min_sec:
            msg = "dream_worker_sleep_max_sec must be >= dream_worker_sleep_min_sec"
            raise ValueError(msg)
        return self


plugin_webui = install_hot_reload_config(Config, config_module=__name__)
get_dream_config = plugin_webui.get
plugin_config = plugin_config_proxy(get_dream_config)
