"""分片运行时上下文：插件与 features 优先从此模块读取角色与代表牛，避免散落 import。"""

from __future__ import annotations

from src.platform.shard.local_representative import (
    is_local_worker_representative,
    local_worker_representative_bot_id,
)
from src.platform.shard.registry.config import BotRole, get_shard_registry_settings, is_sharding_active

__all__ = [
    "BotRole",
    "is_hub",
    "is_local_representative",
    "is_unified",
    "is_worker",
    "local_representative_bot_id",
    "role",
    "shard_id",
    "sharding_active",
]


def sharding_active() -> bool:
    return is_sharding_active()


def role() -> BotRole:
    return get_shard_registry_settings().role


def shard_id() -> int:
    return int(get_shard_registry_settings().shard_id)


def is_unified() -> bool:
    return role() == "unified"


def is_hub() -> bool:
    return role() == "hub"


def is_worker() -> bool:
    return role() == "worker"


def local_representative_bot_id() -> int | None:
    return local_worker_representative_bot_id()


def is_local_representative(bot_id: int) -> bool:
    return is_local_worker_representative(bot_id)
