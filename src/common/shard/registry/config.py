"""分片注册表环境配置（hub / worker 共用，读 .env）。"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.common.config.dotenv import merged_repo_dotenv_upper

BotRole = Literal["unified", "hub", "worker"]


def _env_str(name: str, default: str = "") -> str:
    merged = merged_repo_dotenv_upper()
    if name in os.environ:
        return (os.environ.get(name, default) or "").strip()
    return (merged.get(name) or default).strip()


def _env_int(name: str, default: int) -> int:
    raw = _env_str(name, str(default))
    try:
        return int(raw)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = _env_str(name, "").lower()
    if not raw:
        return default
    return raw not in ("0", "false", "no", "off")


class ShardRegistrySettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    enabled: bool = Field(
        default=False,
        description="启用多进程分片；false 时保持单进程（unified）行为。",
    )
    role: BotRole = Field(
        default="unified",
        description="unified=单进程；hub=控制台+协议端+relogin；worker=仅承载分片内牛牛连接。",
    )
    shard_id: int = Field(
        default=0,
        ge=0,
        le=63,
        description="worker 分片编号（0 起）；hub/unified 忽略。",
    )
    bots_per_shard: int = Field(
        default=5,
        ge=1,
        le=32,
        description="每个 worker 进程目标承载的牛牛账号数。",
    )
    hub_port: int = Field(
        default=8088,
        ge=1,
        le=65535,
        description="hub HTTP 端口（WebUI、协议端管理页、relogin 所在进程）。",
    )
    worker_base_port: int = Field(
        default=8090,
        ge=1,
        le=65535,
        description="worker-0 的 HTTP/OneBot 端口；shard N 为 base+N。",
    )
    ws_path: str = Field(
        default="/onebot/v11/ws",
        description="OneBot 反向 WS 路径（与各 worker 一致）。",
    )
    ws_host: str = Field(
        default="",
        description="写入协议端账号的 WS 主机；留空则用 HOST/.env 或 127.0.0.1。",
    )


@lru_cache(maxsize=1)
def get_shard_registry_settings() -> ShardRegistrySettings:
    role_raw = _env_str("PALLAS_BOT_ROLE", "unified").lower()
    role: BotRole = role_raw if role_raw in ("unified", "hub", "worker") else "unified"
    return ShardRegistrySettings(
        enabled=_env_bool("PALLAS_SHARD_ENABLED", False),
        role=role,
        shard_id=_env_int("PALLAS_SHARD_ID", 0),
        bots_per_shard=_env_int("PALLAS_SHARD_BOTS_PER", 5),
        hub_port=_env_int("PALLAS_SHARD_HUB_PORT", _env_int("PORT", 8088)),
        worker_base_port=_env_int("PALLAS_SHARD_WORKER_BASE_PORT", 8090),
        ws_path=_env_str("PALLAS_SHARD_WS_PATH", "/onebot/v11/ws") or "/onebot/v11/ws",
        ws_host=_env_str("PALLAS_SHARD_WS_HOST", _env_str("HOST", "127.0.0.1")),
    )


def is_sharding_active() -> bool:
    s = get_shard_registry_settings()
    return s.enabled and s.role != "unified"
