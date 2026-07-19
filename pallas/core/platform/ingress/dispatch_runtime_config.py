from __future__ import annotations

from threading import Lock
from typing import Self

from pydantic import BaseModel, ConfigDict, Field

from pallas.console.webui.field_help import field_help
from pallas.core.foundation.config.dotenv import repo_env_raw_value, repo_layered_dotenv_files_exist

_config_lock = Lock()
_cached: IngressDispatchRuntimeConfig | None = None


def dispatch_env_raw(name_upper: str) -> str | None:
    raw = repo_env_raw_value(name_upper)
    if raw is not None:
        text = str(raw).strip()
        return text or None
    if not repo_layered_dotenv_files_exist():
        try:
            from nonebot import get_driver

            cfg = get_driver().config
            attr = name_upper.lower()
            if attr in (getattr(cfg, "model_fields_set", None) or set()):
                val = getattr(cfg, attr, None)
                if val is None:
                    return None
                return str(val).strip()
        except ValueError:
            pass
    return None


def dispatch_env_bool(name_upper: str, *, default: bool) -> bool:
    raw = dispatch_env_raw(name_upper)
    if raw is None:
        return default
    text = raw.lower()
    if text in ("0", "false", "no", "off"):
        return False
    if text in ("1", "true", "yes", "on"):
        return True
    return default


def dispatch_env_int(name_upper: str, *, default: int, minimum: int, maximum: int) -> int:
    raw = dispatch_env_raw(name_upper)
    if raw is None:
        return default
    try:
        return max(minimum, min(maximum, int(raw)))
    except ValueError:
        return default


def dispatch_env_float(name_upper: str, *, default: float, minimum: float) -> float:
    raw = dispatch_env_raw(name_upper)
    if raw is None:
        return default
    try:
        return max(minimum, float(raw))
    except ValueError:
        return default


class IngressDispatchRuntimeConfig(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    matcher_dispatch_enabled: bool = Field(
        default=True,
        description=field_help(
            "减少群消息在插件里反复试匹配的开销，闲聊时跳过纯口令类插件",
            "选开或关；多牛、插件多的群一般保持开启",
            "关闭后恢复框架默认匹配方式；保存后立即生效",
        ),
    )
    matcher_dispatch_overload_threshold: int = Field(
        default=24,
        ge=1,
        le=256,
        description=field_help(
            "单条群消息需检查的插件过多时，视为入站过载并暂缓后台任务",
            "填正整数，默认 24；插件特别多时可试 32～48",
            "触发后社区语料 prefetch 等后台任务会暂时让路",
        ),
    )
    route_index_enabled: bool = Field(
        default=True,
        description=field_help(
            "按口令前缀或全文只激活可能相关的插件，减少无关扫描",
            "选开或关；一般保持开启",
            "关闭后每条消息仍会尝试全部插件 matcher",
        ),
    )
    route_index_strict: bool = Field(
        default=False,
        description=field_help(
            "未收录的口令是否还允许回退到全量插件扫描",
            "关表示漏网口令仍有机会被匹配；开表示只认索引里列出的插件",
            "稳定运行前建议保持关闭，避免口令无反应",
        ),
    )
    dispatch_lanes_enabled: bool = Field(
        default=True,
        description=field_help(
            "按口令、闲聊、数据库、外呼等档位限制同时运行的插件数量",
            "选开或关；一般保持开启",
            "关闭后重命令可能占满数据库连接或拖慢整群回复",
        ),
    )
    lane_acquire_timeout_sec: float = Field(
        default=1.0,
        ge=0.0,
        le=30.0,
        description=field_help(
            "某个插件等待空闲档位最多等多久",
            "填秒数，默认 1.0；繁忙群可试 0.5～2.0",
            "超时则跳过该次执行；口令流量可能收到忙回复",
        ),
    )
    lane_wait_overload_ms: int = Field(
        default=250,
        ge=50,
        le=5000,
        description=field_help(
            "档位排队过久时触发全站过载信号",
            "填毫秒，默认 250",
            "与首页「入站调度」面板中的过载计数联动",
        ),
    )
    lane_busy_reply: bool = Field(
        default=True,
        description=field_help(
            "口令档已满时是否向群里发一句「忙不过来」的人设回复",
            "选开或关；一般保持开启",
            "关闭时静默丢弃，群友可能误以为没触发命令",
        ),
    )
    lane_command: int = Field(
        default=16,
        ge=1,
        le=128,
        description=field_help(
            "同时执行多少条口令类命令",
            "填正整数，默认 16",
            "保存后立即调整档位上限",
        ),
    )
    lane_chat: int = Field(
        default=32,
        ge=1,
        le=256,
        description=field_help(
            "同时执行多少条闲聊、接话类被动插件",
            "填正整数，默认 32",
            "保存后立即调整档位上限",
        ),
    )
    lane_storage: int = Field(
        default=8,
        ge=1,
        le=64,
        description=field_help(
            "同时执行多少条频繁读写数据库的插件",
            "填正整数，默认 8；不宜超过 PG 连接池大小",
            "数据库压力大时会自动减半",
        ),
    )
    lane_remote: int = Field(
        default=4,
        ge=1,
        le=64,
        description=field_help(
            "同时执行多少条画图、AI、HTTP 等对外请求的重命令",
            "填正整数，默认 4",
            "保存后立即调整档位上限",
        ),
    )
    send_queue_enabled: bool = Field(
        default=True,
        description=field_help(
            "把发送群消息等出站动作排队，避免全员同响时瞬间打满协议端",
            "选开或关；一般保持开启",
            "关闭后发送请求直连协议端",
        ),
    )
    send_queue_workers: int = Field(
        default=2,
        ge=1,
        le=16,
        description=field_help(
            "有多少条线程从队列里取消息并发送",
            "填正整数，默认 2",
            "变更后需重启 Bot 才生效",
        ),
    )
    send_queue_max_depth: int = Field(
        default=256,
        ge=32,
        le=4096,
        description=field_help(
            "出站队列最多积压多少条待发送",
            "填正整数，默认 256；队列满时点赞等低优先级动作可能被丢弃",
            "保存后立即生效",
        ),
    )
    send_queue_min_interval_ms: int = Field(
        default=50,
        ge=0,
        le=2000,
        description=field_help(
            "同一只牛两次发送之间至少间隔多久",
            "填毫秒，默认 50；填 0 表示不限制",
            "可减轻协议端突发发送压力",
        ),
    )
    send_queue_enqueue_timeout_sec: float = Field(
        default=2.0,
        ge=0.0,
        le=30.0,
        description=field_help(
            "一条发送请求在队列外最多等多久才能入队",
            "填秒数，默认 2.0",
            "超时则放弃该次发送",
        ),
    )

    @classmethod
    def from_env(cls) -> Self:
        pool_size = dispatch_env_int("PG_POOL_SIZE", default=10, minimum=1, maximum=128)
        storage_default = min(8, pool_size)
        return cls(
            matcher_dispatch_enabled=dispatch_env_bool("PALLAS_MATCHER_DISPATCH_ENABLED", default=True),
            matcher_dispatch_overload_threshold=dispatch_env_int(
                "PALLAS_MATCHER_DISPATCH_OVERLOAD_THRESHOLD",
                default=24,
                minimum=1,
                maximum=256,
            ),
            route_index_enabled=dispatch_env_bool("PALLAS_ROUTE_INDEX_ENABLED", default=True),
            route_index_strict=dispatch_env_bool("PALLAS_ROUTE_INDEX_STRICT", default=False),
            dispatch_lanes_enabled=dispatch_env_bool("PALLAS_DISPATCH_LANES_ENABLED", default=True),
            lane_acquire_timeout_sec=dispatch_env_float("PALLAS_LANE_ACQUIRE_TIMEOUT_SEC", default=1.0, minimum=0.0),
            lane_wait_overload_ms=dispatch_env_int(
                "PALLAS_LANE_WAIT_OVERLOAD_MS",
                default=250,
                minimum=50,
                maximum=5000,
            ),
            lane_busy_reply=dispatch_env_bool("PALLAS_LANE_BUSY_REPLY", default=True),
            lane_command=dispatch_env_int("PALLAS_LANE_COMMAND", default=16, minimum=1, maximum=128),
            lane_chat=dispatch_env_int("PALLAS_LANE_CHAT", default=32, minimum=1, maximum=256),
            lane_storage=dispatch_env_int("PALLAS_LANE_STORAGE", default=storage_default, minimum=1, maximum=64),
            lane_remote=dispatch_env_int("PALLAS_LANE_REMOTE", default=4, minimum=1, maximum=64),
            send_queue_enabled=dispatch_env_bool("PALLAS_SEND_QUEUE_ENABLED", default=True),
            send_queue_workers=dispatch_env_int("PALLAS_SEND_QUEUE_WORKERS", default=2, minimum=1, maximum=16),
            send_queue_max_depth=dispatch_env_int("PALLAS_SEND_QUEUE_MAX_DEPTH", default=256, minimum=32, maximum=4096),
            send_queue_min_interval_ms=dispatch_env_int(
                "PALLAS_SEND_QUEUE_MIN_INTERVAL_MS",
                default=50,
                minimum=0,
                maximum=2000,
            ),
            send_queue_enqueue_timeout_sec=dispatch_env_float(
                "PALLAS_SEND_QUEUE_ENQUEUE_TIMEOUT_SEC",
                default=2.0,
                minimum=0.0,
            ),
        )


def clear_ingress_dispatch_runtime_config_cache() -> None:
    global _cached
    with _config_lock:
        _cached = None


def get_ingress_dispatch_runtime_config() -> IngressDispatchRuntimeConfig:
    global _cached
    with _config_lock:
        if _cached is None:
            _cached = IngressDispatchRuntimeConfig.from_env()
        return _cached
