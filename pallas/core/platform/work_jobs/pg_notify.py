"""PostgreSQL NOTIFY 助手：通知 delivery dispatcher 有可投递任务。"""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

DELIVERY_READY_CHANNEL = "sticker_vision.delivery_ready"

# A module-level slot so tests / callers can override the actual notification
# without opening a real DB session (the store callback wiring happens in a later task).
_notify_impl: Callable[[], Awaitable[None]] | None = None


def set_notify_delivery_ready_impl(fn: Callable[[], Awaitable[None]] | None) -> None:
    global _notify_impl
    _notify_impl = fn


async def notify_delivery_ready() -> None:
    if _notify_impl is not None:
        await _notify_impl()
        return
    from sqlalchemy import text

    from pallas.core.foundation.db import get_db_backend
    from pallas.core.foundation.db.repository_pg import get_session

    backend = str(get_db_backend() or "").strip().lower()
    if backend != "postgresql":
        return

    async with get_session() as session:
        await session.execute(text(f"SELECT pg_notify('{DELIVERY_READY_CHANNEL}', '1')"))
        await session.commit()


async def listen_delivery_ready(on_notify: Callable[[], Awaitable[None]] | None = None) -> None:
    """在一条专用异步连接上 LISTEN delivery ready 频道并阻塞到取消。

    worker 辅进程在写完成时同事务 ``pg_notify`` 广播；主进程借由本函数
    立即唤醒 dispatcher，而非只靠 2s 兜底轮询。仅 postgresql 后端才会监听。
    """
    from pallas.core.foundation.db import get_db_backend

    backend = str(get_db_backend() or "").strip().lower()
    if backend != "postgresql":
        return

    from pallas.core.foundation.db.repository_pg import pg_engine

    engine = pg_engine()
    if engine is None:
        return

    async def wrapper(asyncpg_conn, pid: int, channel: str, payload: str) -> None:
        if on_notify is None:
            return
        with contextlib.suppress(Exception):
            await on_notify()

    # raw_connection 不经 SQLAlchemy 事务；driver_connection 即原生 asyncpg 连接。
    raw = await engine.raw_connection()
    asyncpg_conn = raw.driver_connection
    try:
        await asyncpg_conn.add_listener(DELIVERY_READY_CHANNEL, wrapper)
        try:
            await asyncio.Event().wait()
        finally:
            with contextlib.suppress(Exception):
                await asyncpg_conn.remove_listener(DELIVERY_READY_CHANNEL, wrapper)
    finally:
        # 监听连接长期占用，归池时若池内空闲位已满（优雅退出时必然如此）会走
        # overflow 硬关闭路径，在无 greenlet 上下文处 await asyncpg close，
        # 抛 MissingGreenlet 且连接不会被真正关闭。detach 只是池侧登记（无 IO），
        # 随后用原生 asyncpg close 真正异步关闭。
        with contextlib.suppress(Exception):
            raw.detach()
        with contextlib.suppress(Exception):
            await asyncpg_conn.close()
