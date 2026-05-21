"""入站门控 / fast lane"""

from __future__ import annotations

from functools import cached_property
from threading import Lock
from typing import Self

from pydantic import BaseModel, ConfigDict, Field

from src.common.env_dotenv import repo_env_raw_value, repo_layered_dotenv_files_exist

_config_lock = Lock()
_cached_ingress_config: IngressConfig | None = None


def _bool_from_str(raw: str, *, default: bool) -> bool:
    v = (raw or "").strip().lower()
    if not v:
        return default
    return v not in ("0", "false", "no", "off")


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
                if isinstance(val, bool):
                    return "1" if val else "0"
                return str(val).strip()
        except ValueError:
            pass
    return default


def _split_csv_texts(raw: str, *, fallback: tuple[str, ...]) -> tuple[str, ...]:
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    return tuple(parts) if parts else fallback


_DEFAULT_GREETING_FANOUT = ("牛牛", "帕拉斯")


class IngressConfig(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    ingress_fast_lane_enabled: bool = Field(
        default=True,
        description=(
            "启用 Fast Lane：私聊、以命令前缀开头的群消息、@ 牛牛、决斗/八角笼等不占慢路径槽，"
            "利于牛牛帮助等命令优先排队。WebUI 保存后立即生效。"
        ),
    )
    ingress_slow_concurrency: int = Field(
        default=24,
        ge=1,
        le=512,
        description=(
            "慢路径主槽并发上限（仅：已分片且非 Fast Lane 的群水群）。"
            "多牛同群建议 16～24；与 dispatch worker 解耦，勿盲目拉到 96。"
        ),
    )
    ingress_slow_dispatch_workers: int = Field(
        default=0,
        ge=0,
        le=512,
        description=(
            "水群 dispatch 消费协程数；0 表示自动 min(主槽并发, 24)。宜 ≤ 主槽并发，避免大量 worker 同时挤占事件循环。"
        ),
    )
    ingress_slow_acquire_sec: float = Field(
        default=4.0,
        ge=0.1,
        le=120.0,
        description=(
            "慢路径等主槽的最长等待（秒）。超时后按「直接丢弃」或走溢出槽处理；不影响 Fast Lane 命令本身是否走慢路径。"
        ),
    )
    ingress_slow_drop_on_timeout: bool = Field(
        default=False,
        description=(
            "主槽等满超时后是否直接丢弃该条水群（不进溢出槽）。"
            "false：先尝试溢出槽；true：高峰主动丢水群，保牛牛命令与私聊响应（推荐繁忙群开启）。"
        ),
    )
    ingress_slow_overflow_concurrency: int = Field(
        default=48,
        ge=0,
        le=512,
        description=(
            "主槽满且未勾选「直接丢弃」时，额外并发处理的水群条数（溢出槽）。"
            "0 表示无限放行（易拖死全局队列，生产勿用）；繁忙多群建议 32～48。"
        ),
    )
    ingress_multi_bot_shard_enabled: bool = Field(
        default=True,
        description=(
            "多牛牛同群时，除 greeting 精确匹配全员同响、决斗主持牛外，每条群消息仅一只牛进入 matcher，"
            "避免 N 个连接重复处理同一句。约 22 号时可将事件量降到约 1/22。"
        ),
    )
    fast_lane_command_prefix: str = Field(
        default="牛牛",
        description=("群纯文本以此前缀开头视为 Fast Lane（如牛牛帮助、牛牛决斗），与私聊一样不占慢路径槽。"),
    )
    greeting_fanout_texts: str = Field(
        default="牛牛,帕拉斯",
        description=(
            "greeting 插件精确匹配这些全文时所有在线牛同响（逗号分隔），不做入站分片；其它消息仍走分片与慢路径。"
        ),
    )
    ingress_notice_gate_enabled: bool = Field(
        default=True,
        description=("对 Notice（表情点赞、戳一戳、撤回等）采样保留并分片，减轻大群无效事件风暴。"),
    )
    notice_emoji_like_keep: float = Field(
        default=0.12,
        ge=0.0,
        le=1.0,
        description="群消息表情点赞类 Notice 保留概率（0～1）。大群可降至 0.08 以下。",
    )
    notice_poke_keep: float = Field(
        default=0.25,
        ge=0.0,
        le=1.0,
        description="戳一戳 Notice 保留概率（0～1）。",
    )
    notice_recall_keep: float = Field(
        default=0.05,
        ge=0.0,
        le=1.0,
        description="撤回 Notice 保留概率（0～1）。",
    )
    notice_default_keep: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="未单独列出的其它 Notice 保留概率（0～1）。",
    )

    @cached_property
    def greeting_fanout_set(self) -> frozenset[str]:
        return frozenset(_split_csv_texts(self.greeting_fanout_texts, fallback=_DEFAULT_GREETING_FANOUT))

    @classmethod
    def from_env(cls) -> Self:
        try:
            slow_concurrency = int(_ingress_env_str("PALLAS_INGRESS_SLOW_CONCURRENCY", default="24") or "24")
        except ValueError:
            slow_concurrency = 24
        slow_concurrency = max(1, min(512, slow_concurrency))
        try:
            slow_acquire = float(_ingress_env_str("PALLAS_INGRESS_SLOW_ACQUIRE_SEC", default="4") or "4")
        except ValueError:
            slow_acquire = 4.0
        slow_acquire = max(0.1, min(120.0, slow_acquire))
        try:
            slow_overflow = int(_ingress_env_str("PALLAS_INGRESS_SLOW_OVERFLOW", default="48") or "48")
        except ValueError:
            slow_overflow = 48
        slow_overflow = max(0, min(512, slow_overflow))
        try:
            slow_dispatch_workers = int(_ingress_env_str("PALLAS_INGRESS_SLOW_DISPATCH_WORKERS", default="0") or "0")
        except ValueError:
            slow_dispatch_workers = 0
        slow_dispatch_workers = max(0, min(512, slow_dispatch_workers))

        def prob(key: str, default: str) -> float:
            try:
                return max(0.0, min(1.0, float(_ingress_env_str(key, default=default) or default)))
            except ValueError:
                return float(default)

        return cls(
            ingress_fast_lane_enabled=_bool_from_str(
                _ingress_env_str("PALLAS_INGRESS_FAST_LANE", default="true"),
                default=True,
            ),
            ingress_slow_concurrency=slow_concurrency,
            ingress_slow_dispatch_workers=slow_dispatch_workers,
            ingress_slow_acquire_sec=slow_acquire,
            ingress_slow_drop_on_timeout=_bool_from_str(
                _ingress_env_str("PALLAS_INGRESS_SLOW_DROP", default="false"),
                default=False,
            ),
            ingress_slow_overflow_concurrency=slow_overflow,
            ingress_multi_bot_shard_enabled=_bool_from_str(
                _ingress_env_str("PALLAS_INGRESS_MULTI_BOT_SHARD", default="true"),
                default=True,
            ),
            fast_lane_command_prefix=_ingress_env_str("PALLAS_INGRESS_FAST_LANE_PREFIX", default="牛牛") or "牛牛",
            greeting_fanout_texts=_ingress_env_str(
                "PALLAS_INGRESS_FANOUT_GREETING",
                default="牛牛,帕拉斯",
            ),
            ingress_notice_gate_enabled=_bool_from_str(
                _ingress_env_str("PALLAS_INGRESS_NOTICE_GATE", default="true"),
                default=True,
            ),
            notice_emoji_like_keep=prob("PALLAS_NOTICE_EMOJI_LIKE_KEEP", "0.12"),
            notice_poke_keep=prob("PALLAS_NOTICE_POKE_KEEP", "0.25"),
            notice_recall_keep=prob("PALLAS_NOTICE_RECALL_KEEP", "0.05"),
            notice_default_keep=prob("PALLAS_NOTICE_DEFAULT_KEEP", "1.0"),
        )


def clear_ingress_config_cache() -> None:
    global _cached_ingress_config
    with _config_lock:
        _cached_ingress_config = None


def get_ingress_config() -> IngressConfig:
    global _cached_ingress_config
    with _config_lock:
        if _cached_ingress_config is None:
            _cached_ingress_config = IngressConfig.from_env()
        return _cached_ingress_config
