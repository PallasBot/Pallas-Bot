"""分片模式下做梦相关的 fleet 名册与漂流目标解析。"""

from __future__ import annotations

import asyncio

from nonebot import get_bots

from src.platform.shard import context as shard_ctx


def dream_history_bot_ids(process_fallback_self_id: int) -> list[int]:
    """参与历史梦库采样的牛牛 QQ；分片时为全集群在线 catalog，单进程为本进程连接。"""
    if shard_ctx.sharding_active():
        from src.platform.multi_bot.fleet import get_catalog_bot_ids
        from src.platform.shard.presence import get_cluster_online_bot_ids

        ids = set(get_catalog_bot_ids()) & set(get_cluster_online_bot_ids())
    else:
        try:
            ids = {int(b.self_id) for b in get_bots().values()}
        except Exception:
            ids = set()
    if not ids:
        return [process_fallback_self_id]
    ids.add(process_fallback_self_id)
    return sorted(ids)


async def collect_drift_peer_group_ids(
    bot_id: int,
    source_group_id: int,
    local_targets: list[int],
) -> set[int]:
    """联机梦漂流目标：本进程活跃群 + 分片时其它 worker 上的同行群。"""
    targets = set(local_targets)
    if shard_ctx.sharding_active():
        from src.platform.shard.coord.dream_drift import list_peer_dream_groups_sync

        remote_targets = await asyncio.to_thread(
            list_peer_dream_groups_sync,
            bot_id,
            exclude_group_id=source_group_id,
        )
        targets.update(remote_targets)
    return targets
