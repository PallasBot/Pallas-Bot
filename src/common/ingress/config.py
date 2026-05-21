"""分片 worker：全员同响（跳过 ingress claim）明文白名单。"""

from __future__ import annotations

from functools import cached_property
from threading import Lock
from typing import Self

from pydantic import BaseModel, ConfigDict, Field

from src.common.config.dotenv import repo_env_raw_value, repo_layered_dotenv_files_exist

_config_lock = Lock()
_cached: IngressFanoutConfig | None = None

_DEFAULT_FANOUT = ("牛牛", "帕拉斯", "牛牛报数", "牛牛出列")


def _ingress_env_str(name_upper: str, *, default: str = "") -> str:
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
                if val is None:
                    return default
                return str(val).strip()
        except ValueError:
            pass
    return default


def _split_csv_texts(raw: str, *, fallback: tuple[str, ...]) -> tuple[str, ...]:
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    return tuple(parts) if parts else fallback


class IngressFanoutConfig(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    greeting_fanout_texts: str = Field(
        default="牛牛,帕拉斯,牛牛报数,牛牛出列",
        description=(
            "分片下同群各牛均处理（不做 ingress claim）的群消息明文，逗号分隔、须与全文精确匹配。"
            "可含招呼语、牛牛报数、牛牛赞我等；WebUI 保存后立即生效。"
        ),
    )

    @cached_property
    def fanout_set(self) -> frozenset[str]:
        return frozenset(_split_csv_texts(self.greeting_fanout_texts, fallback=_DEFAULT_FANOUT))

    @classmethod
    def from_env(cls) -> Self:
        return cls(
            greeting_fanout_texts=_ingress_env_str(
                "PALLAS_INGRESS_FANOUT_GREETING",
                default="牛牛,帕拉斯,牛牛报数,牛牛出列",
            ),
        )


def clear_ingress_fanout_config_cache() -> None:
    global _cached
    with _config_lock:
        _cached = None


def get_ingress_fanout_config() -> IngressFanoutConfig:
    global _cached
    with _config_lock:
        if _cached is None:
            _cached = IngressFanoutConfig.from_env()
        return _cached
