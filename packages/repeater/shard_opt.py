"""分片 worker 下复读插件的运行时优化。"""

from __future__ import annotations

from pallas.core.platform.shard import context as shard_ctx


def repeater_worker_handles_message(bot_id: int) -> bool:
    """群消息入口统一放开到本 worker 本地牛，由后续去重/claim 收敛到单牛或 fanout。"""
    if not shard_ctx.sharding_active():
        return True
    return True


def local_connected_bot_ids() -> frozenset[int]:
    """本 worker 当前已连接的牛牛 QQ 集合。"""
    try:
        from nonebot import get_bots
    except Exception:
        return frozenset()
    return frozenset(int(key) for key in get_bots() if str(key).isdigit())


def repeater_scheduler_runs_on_worker() -> bool:
    """主动发言定时任务：分片时仅代表牛所在 worker 执行，减少重复扫描。"""
    if not shard_ctx.sharding_active():
        return True
    return shard_ctx.local_representative_bot_id() is not None


def repeater_maintenance_runs_on_worker() -> bool:
    """跨 worker 全局维护：分片时仅 shard 0 执行。"""
    if not shard_ctx.sharding_active():
        return True
    return shard_ctx.shard_id() == 0
