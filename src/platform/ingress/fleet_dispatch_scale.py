"""多牛进程内舰队规模，用于 ingress dispatch 默认预算缩放。"""

from __future__ import annotations


def connected_bot_count() -> int:
    """与 ingress_gate 一致：优先协议/catalog 舰队规模，再与当前 WS 在线数取较大值。"""
    count = 0
    try:
        from src.platform.multi_bot.fleet import get_fleet_bot_ids

        count = len(get_fleet_bot_ids())
    except Exception:
        pass
    try:
        from nonebot import get_bots

        count = max(count, len(get_bots()))
    except ValueError:
        pass
    return max(1, count)


def scaled_dispatch_int(base: int, *, per_bot: int = 2, cap: int = 64) -> int:
    count = connected_bot_count()
    return min(cap, max(base, count * per_bot))
