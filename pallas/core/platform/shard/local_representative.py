"""分片 worker：每进程仅一只「代表牛」负责跨进程文件 claim / fanout 类指令。"""

from __future__ import annotations


def local_worker_representative_bot_id() -> int | None:
    """本 worker 已连接牛牛中最小 QQ；无连接时返回 None。"""
    try:
        from nonebot import get_bots
    except Exception:
        return None
    ids = [int(key) for key in get_bots() if str(key).isdigit()]
    if not ids:
        return None
    return min(ids)


def is_local_worker_representative(bot_id: int) -> bool:
    rep = local_worker_representative_bot_id()
    if rep is None:
        return True
    return int(bot_id) == rep
