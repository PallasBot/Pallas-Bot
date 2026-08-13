"""带可控关机时长的 ASGI 服务启动。

裸 ``nonebot.run()`` 底层用 ``asyncio.run`` 管理 uvicorn，其收尾阶段会无超时等待
默认线程池中的线程；停止时若存在 in-flight 的网络/Redis 调用，进程会被拖住数秒到数十秒。
这里改为手动管理事件循环，给 executor 关闭设置超时，超时后强制退出并记录关机各阶段日志。
"""

from __future__ import annotations

import asyncio
import os
import threading
import time
from typing import Any

from nonebot import logger

_EXECUTOR_TIMEOUT = 5.0
_GRACEFUL_SHUTDOWN_TIMEOUT = 8.0

# uvloop 的默认 executor 线程名为 ThreadPoolExecutor-N_x（非 asyncio_x）
_EXECUTOR_THREAD_PREFIXES = ("asyncio_", "ThreadPoolExecutor-")


def _uvicorn_log_config() -> dict[str, Any]:
    """与 NoneBot FastAPI driver 保持一致，让 uvicorn 日志进入 loguru。"""
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "handlers": {
            "default": {
                "class": "nonebot.log.LoguruHandler",
            },
        },
        "loggers": {
            "uvicorn.error": {"handlers": ["default"], "level": "INFO"},
            "uvicorn.access": {"handlers": ["default"], "level": "INFO"},
        },
    }


def _executor_worker_threads() -> list[threading.Thread]:
    """返回默认 executor 的工作线程（asyncio / uvloop 命名）。"""
    return [
        thread
        for thread in threading.enumerate()
        if (thread.name or "").startswith(_EXECUTOR_THREAD_PREFIXES) and thread.is_alive()
    ]


def _drain_executor(loop: asyncio.AbstractEventLoop, *, executor_timeout: float) -> bool:
    """限时关闭默认线程池；超时返回 True，并断开 executor 避免 loop.close() 无超时 join。

    uvloop 的 ``_default_executor`` 是 Cython 私有属性，getattr 拿不到，须走
    ``shutdown_default_executor(timeout=…)`` 统一排干，超时后靠残留线程判定。
    """
    deadline = time.monotonic() + executor_timeout

    def _worker_threads_alive() -> bool:
        return bool(
            thread
            for thread in threading.enumerate()
            if (thread.name or "").startswith(_EXECUTOR_THREAD_PREFIXES) and thread.is_alive()
        )

    executor = getattr(loop, "_default_executor", None)
    if executor is None:
        # uvloop：官方入口内部 await 排干，timeout 参数只作用于事后 join，
        # 须用 wait_for 外层限时；正常排干则返回，超时后 shutdown(wait=False)
        # 已中断等待，只能靠残留工作线程判定是否真的排干。
        shutdown_default_executor = getattr(loop, "shutdown_default_executor", None)
        if shutdown_default_executor is None:
            return False
        try:
            loop.run_until_complete(asyncio.wait_for(shutdown_default_executor(timeout=1.0), timeout=executor_timeout))
            return False
        except TimeoutError:
            return _worker_threads_alive()

    executor.shutdown(wait=False)
    timed_out = False
    for thread in list(getattr(executor, "_threads", ())):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            timed_out = True
            continue
        thread.join(timeout=remaining)
        if thread.is_alive():
            timed_out = True
    try:
        loop.set_default_executor(None)
    except TypeError:
        pass
    return timed_out


def _shutdown_loop(loop: asyncio.AbstractEventLoop, *, executor_timeout: float) -> bool:
    """取消残留任务并关闭 async gens / executor；executor 超时返回 True。"""
    start = time.monotonic()
    pending = [task for task in asyncio.all_tasks(loop) if not task.done()]
    if pending:
        for task in pending:
            task.cancel()
        loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
    logger.info("[ShutDown] 已取消 [{}] 个残留任务", len(pending))
    loop.run_until_complete(loop.shutdown_asyncgens())
    logger.info("[ShutDown] 异步生成器已关闭，开始限时 [{}]s 排干线程池", executor_timeout)
    timed_out = _drain_executor(loop, executor_timeout=executor_timeout)
    if timed_out:
        logger.warning(
            "[ShutDown] 线程池超过 [{}]s 未排干，直接退出不等待残留线程",
            executor_timeout,
        )
    else:
        logger.info("[ShutDown] 线程池排干完成，耗时 [{:.1f}]s", time.monotonic() - start)
    return timed_out


def run_asgi_server(
    *,
    host: str | None = None,
    port: int | None = None,
    executor_timeout: float = _EXECUTOR_TIMEOUT,
    **kwargs: Any,
) -> None:
    """以受控关机时长运行 NoneBot 的 uvicorn 服务；替代裸 ``nonebot.run()``。"""
    import uvicorn
    from nonebot import get_driver

    driver = get_driver()
    if not hasattr(driver, "server_app"):
        driver.run(host=host, port=port, **kwargs)
        return
    config = uvicorn.Config(
        driver.server_app,
        host=host or str(driver.config.host),
        port=port or driver.config.port,
        log_config=_uvicorn_log_config(),
        # NoneBot on_shutdown / 存量连接可能拖住 shutdown，限时让 serve() 返回后走受控收尾
        timeout_graceful_shutdown=_GRACEFUL_SHUTDOWN_TIMEOUT,
        **kwargs,
    )
    server = uvicorn.Server(config)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    exit_code = 0
    timed_out = False
    try:
        loop.run_until_complete(server.serve())
    except KeyboardInterrupt:
        logger.info("[ShutDown] 收到用户中断")
    except BaseException:
        logger.exception("[ShutDown] 服务运行异常")
        exit_code = 1
    finally:
        timed_out = _shutdown_loop(loop, executor_timeout=executor_timeout)
        asyncio.set_event_loop(None)
        try:
            loop.close()
        finally:
            logger.complete()
            if timed_out:
                # 跳过解释器对线程池线程的 join，避免被残留 in-flight 线程拖住停止
                os._exit(exit_code)
