"""unified Bot 的跨平台探活与自动重启。"""

from __future__ import annotations

import logging
import signal
import time
import urllib.error
import urllib.request
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

from pallas.console.cli.bot_process import run_bot_lifecycle
from pallas.console.cli.unified_lifecycle import read_listen_port

logger = logging.getLogger("pallas.daemon")


def probe_health(port: int, *, timeout: float = 5.0) -> bool:
    url = f"http://127.0.0.1:{int(port)}/pallas/api/health"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(url, method="GET", headers={"User-Agent": "pallas-daemon/1"})
    try:
        with opener.open(request, timeout=timeout) as response:
            return 200 <= int(response.status) < 300
    except (OSError, urllib.error.URLError):
        return False


def run_daemon(
    *,
    interval: float = 15.0,
    timeout: float = 5.0,
    fail_threshold: int = 3,
    cooldown: float = 5.0,
    port: int | None = None,
    probe: Callable[[int], bool] = probe_health,
    lifecycle: Callable[..., int] = run_bot_lifecycle,
    sleep: Callable[[float], Any] = time.sleep,
) -> int:
    """启动并守护 unified；测试可注入探活、生命周期和 sleep 实现。"""
    if interval <= 0 or timeout <= 0 or cooldown < 0:
        raise ValueError("interval/timeout 必须大于 0，cooldown 不能小于 0")
    if fail_threshold < 1:
        raise ValueError("fail_threshold 必须大于 0")

    listen_port = int(port or read_listen_port())
    stopping = False

    def stop(_signum: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True

    previous_handlers = {}
    for signum in (signal.SIGINT, signal.SIGTERM):
        previous_handlers[signum] = signal.signal(signum, stop)

    try:
        logger.info("启动 unified daemon，探活端口 [%s]", listen_port)
        start_code = lifecycle("start", mode="unified", extra_args=["--detach"])
        if start_code != 0:
            return start_code

        failures = 0
        while not stopping:
            if probe(listen_port):
                if failures:
                    logger.info("Bot health 已恢复")
                failures = 0
            else:
                failures += 1
                logger.warning("Bot health 探活失败 [%s/%s]", failures, fail_threshold)
                if failures >= fail_threshold:
                    logger.error("Bot health 连续失败，重启 unified")
                    restart_code = lifecycle(
                        "restart",
                        mode="unified",
                        extra_args=["--detach", "--skip-port-sync"],
                    )
                    if restart_code != 0:
                        logger.error("unified 重启失败，退出码 [%s]", restart_code)
                        return restart_code
                    failures = 0
                    sleep(cooldown)
                    continue
            sleep(interval)
    finally:
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)
        lifecycle("stop", mode="unified")
        logger.info("unified daemon 已停止")
    return 0
