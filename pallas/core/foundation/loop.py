"""事件循环优化：显式启用 uvloop（Linux 上可用时），并兜底未检索的 asyncio 任务异常。"""

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


def install_loop_exception_logging() -> None:
    """为当前事件循环挂载异常兜底：未检索的 asyncio 任务异常转发到 loguru ERROR。

    这类异常（如 "Task exception was never retrieved"）默认只打到 stderr，
    绕过 loguru 无法进入 WebUI 报错页；此处转发后可被统一捕获，并链式调用原 handler。
    """
    from nonebot.log import logger

    loop = asyncio.get_running_loop()
    previous = loop.get_exception_handler()

    def _handle(loop, context) -> None:
        exc = context.get("exception")
        message = context.get("message") or "Unhandled exception in event loop"
        if exc is not None:
            logger.error(
                "asyncio unhandled task exception [{}]: {}",
                message,
                exc,
                exc_info=exc,
            )
        else:
            logger.error("asyncio event loop error [{}]", message)
        if previous is not None:
            previous(loop, context)
        else:
            loop.default_exception_handler(context)

    loop.set_exception_handler(_handle)
