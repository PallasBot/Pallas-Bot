"""事件循环优化：显式启用 uvloop（Linux 上可用时）。"""

from __future__ import annotations

import asyncio
import sys


def install_uvloop() -> bool:
    """安装 uvloop 事件循环策略；不可用（Windows / 未安装）时静默跳过。

    返回是否已安装。
    """
    if sys.platform == "win32":
        return False
    try:
        import uvloop  # noqa: PLC0415
    except ImportError:
        return False
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
    return True
