from __future__ import annotations

from nonebot import get_driver, logger

from pallas.core.foundation.startup_report import register_startup_fact
from pallas.core.platform.bot_runtime.roles import is_hub_role
from pallas.core.platform.ingress.dispatch_stats_logger import (
    start_dispatch_stats_logger,
    stop_dispatch_stats_logger,
)
from pallas.core.platform.ingress.matcher_dispatch import (
    install_matcher_dispatch,
    matcher_dispatch_enabled,
    uninstall_matcher_dispatch,
)
from pallas.core.platform.ingress.route_index import build_route_index, route_index_enabled, route_index_strict
from pallas.core.platform.ingress.send_queue import (
    install_send_queue,
    start_send_queue_workers,
    stop_send_queue_workers,
    uninstall_send_queue,
)

_HOOK_REGISTERED = False


def register_ingress_dispatch_runtime() -> None:
    global _HOOK_REGISTERED
    if _HOOK_REGISTERED or is_hub_role():
        return
    try:
        driver = get_driver()
    except ValueError:
        return

    @driver.on_startup
    async def install_ingress_dispatch_on_startup() -> None:
        if route_index_enabled():
            index = build_route_index()
            register_startup_fact(
                "ingress",
                f"prefix={len(index.prefix_to_modules)} "
                f"exact={len(index.exact_to_modules)} "
                f"modules={len(index.indexed_modules)} "
                f"strict={route_index_strict()}",
            )
        install_send_queue()
        await start_send_queue_workers()
        install_matcher_dispatch()
        start_dispatch_stats_logger()

    @driver.on_shutdown
    async def uninstall_ingress_dispatch_on_shutdown() -> None:
        await stop_dispatch_stats_logger()
        uninstall_matcher_dispatch()
        await stop_send_queue_workers()
        uninstall_send_queue()

    _HOOK_REGISTERED = True
    if matcher_dispatch_enabled():
        logger.debug("bot_runtime: ingress dispatch runtime registered")


def ingress_dispatch_runtime_registered() -> bool:
    return _HOOK_REGISTERED
