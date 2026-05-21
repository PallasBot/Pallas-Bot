"""复读后台 learn：WebUI 通用配置 / .env 运行时（与 NoneBot 插件 Config 字段对齐）。"""

from __future__ import annotations

from threading import Lock
from typing import Self

from pydantic import BaseModel, ConfigDict, Field

from src.common.config.dotenv import repo_env_raw_value, repo_layered_dotenv_files_exist

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
        default=24,
        ge=1,
        le=128,
        description=(
            "后台语料 learn 最大并发。handler 已先接话再入队，此项主要减轻事件循环拥堵、加快牛牛命令排队。"
            "WebUI 保存后立即生效；CPU 充裕可试 32～48。"
        ),
    )
    learn_queue_max_size: int = Field(
        default=2048,
        ge=64,
        le=20000,
        description=(
            "待 learn 队列长度；满则仅丢弃 learn、不影响接话与命令。"
            "WebUI 保存后会重启 learn worker 以应用新容量；极端刷屏时略少学几句。"
        ),
    )

    @classmethod
    def from_env(cls) -> Self:
        try:
            concurrency = int(_learn_env_str("PALLAS_REPEATER_LEARN_CONCURRENCY", default="24") or "24")
        except ValueError:
            concurrency = 24
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
