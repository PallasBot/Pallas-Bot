"""coord Redis 故障日志：独立叶子模块，避免 redis_claim 与 shard.coord 循环导入。"""

from __future__ import annotations

from nonebot.log import logger

from pallas.core.foundation.logging.throttle import log_rate_limited


def log_coord_redis_failure(op: str, err: Exception) -> None:
    """coord Redis 故障限频 warning，避免每消息刷屏。"""
    log_rate_limited(
        logger,
        "warning",
        f"coord_redis.{op}",
        "coord redis {} failed: {}",
        op,
        err,
    )
