"""复读后台 learn 运行时（读 repeater 插件配置，兼容旧调用方）。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from pallas.console.webui.field_help import field_help


class RepeaterLearnRuntimeConfig(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    learn_concurrency: int = Field(
        default=8,
        ge=1,
        le=128,
        description=field_help(
            "后台同时处理多少条「学语料」任务",
            "填正整数，例如 24；机器 CPU 较空闲时可试 32～48",
            "只影响后台学习速度，不影响复读接话和命令回复；保存后立即生效",
        ),
    )
    learn_queue_max_size: int = Field(
        default=2048,
        ge=64,
        le=20000,
        description=field_help(
            "等待学习的消息最多排队多少条",
            "填正整数，例如 2048；队列满时只跳过学习，照常复读和回复命令",
            "保存后会重启后台学习线程以应用新容量；群消息特别多时可适当加大",
        ),
    )


def clear_repeater_learn_runtime_config_cache() -> None:
    """兼容旧调用；学习参数已并入 repeater 插件配置。"""


def get_repeater_learn_runtime_config() -> RepeaterLearnRuntimeConfig:
    from .config import get_repeater_config

    cfg = get_repeater_config()
    return RepeaterLearnRuntimeConfig(
        learn_concurrency=cfg.learn_concurrency,
        learn_queue_max_size=cfg.learn_queue_max_size,
    )
