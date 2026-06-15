"""复读后台 learn：WebUI 通用配置 / .env 运行时。"""

from __future__ import annotations

from threading import Lock
from typing import Self

from pydantic import BaseModel, ConfigDict, Field

from src.console.webui.field_help import field_help
from src.foundation.config.dotenv import repo_env_raw_value, repo_layered_dotenv_files_exist

_config_lock = Lock()
_cached: RepeaterLearnRuntimeConfig | None = None


def _learn_env_str(name_upper: str, *, default: str = "") -> str:
    raw = repo_env_raw_value(name_upper)
    if raw is not None:
        return raw.strip()
    if not repo_layered_dotenv_files_exist():
        try:
            from nonebot import get_driver

            cfg = get_driver().config
            attr = name_upper.lower()
            if attr in (getattr(cfg, "model_fields_set", None) or set()):
                val = getattr(cfg, attr, None)
                if val is not None:
                    return str(val).strip()
        except ValueError:
            pass
    return default


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

    @classmethod
    def from_env(cls) -> Self:
        try:
            concurrency = int(_learn_env_str("PALLAS_REPEATER_LEARN_CONCURRENCY", default="8") or "8")
        except ValueError:
            concurrency = 8
        try:
            queue_max = int(_learn_env_str("PALLAS_REPEATER_LEARN_QUEUE_SIZE", default="2048") or "2048")
        except ValueError:
            queue_max = 2048
        return cls(
            learn_concurrency=max(1, min(128, concurrency)),
            learn_queue_max_size=max(64, min(20_000, queue_max)),
        )


def clear_repeater_learn_runtime_config_cache() -> None:
    global _cached
    with _config_lock:
        _cached = None


def get_repeater_learn_runtime_config() -> RepeaterLearnRuntimeConfig:
    global _cached
    with _config_lock:
        if _cached is None:
            _cached = RepeaterLearnRuntimeConfig.from_env()
        return _cached
