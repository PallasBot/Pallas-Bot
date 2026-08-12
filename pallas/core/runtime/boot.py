"""Bot 启动链：供 bot.py / bot_hub.py / bot_worker.py 调用。"""

from __future__ import annotations

import nonebot
from nonebot.adapters.onebot.v11 import Adapter as ONEBOT_V11Adapter
from nonebot.log import logger

from pallas.console.web import install_nonebot_log_sink
from pallas.core.foundation.config.repo_settings import apply_repo_settings_to_environ
from pallas.core.foundation.db import init_db, install_pg_shutdown_hook
from pallas.core.foundation.logging import (
    apply_stdlib_logging_channel_prefix,
    configure_quiet_library_loggers,
    format_repo_file_log,
    install_repo_console_log_format,
    install_startup_log_noise_patcher,
    resolve_repo_log_level,
)
from pallas.core.foundation.paths import plugin_data_dir
from pallas.core.foundation.startup_report import emit_startup_summary
from pallas.core.platform.bot_runtime import load_plugins_for_role
from pallas.core.shared.adapters import register_onebot_v11_custom_events
from pallas.core.shared.utils.voice_downloader import schedule_ensure_voices
from pallas.product.ban_gate import start_ban_gate_snapshot, stop_ban_gate_snapshot
from pallas.product.llm.startup_probe import install_llm_startup_probe
from pallas.product.message_scrub import start_message_scrub_if_enabled


def apply_repo_settings() -> None:
    apply_repo_settings_to_environ()


def boot() -> nonebot.Driver:
    apply_stdlib_logging_channel_prefix()
    configure_quiet_library_loggers()
    file_log_level = resolve_repo_log_level()
    nonebot.init()
    install_repo_console_log_format()
    install_startup_log_noise_patcher()
    logger.info("[初始化] 运行环境载入中...")
    bot_log_dir = plugin_data_dir("bot", create=True)
    logger.add(
        bot_log_dir / "nonebot_{time:YYYY-MM-DD_HH-mm-ss_SSSSSS}.log",
        level=file_log_level,
        format=format_repo_file_log,
        rotation="50 MB",
        retention="14 days",
        encoding="utf-8",
        enqueue=True,
    )
    logger.info("[初始化] 运行环境已就绪：日志目录 {}，级别 {}", bot_log_dir, file_log_level)
    start_message_scrub_if_enabled()
    install_llm_startup_probe()
    install_nonebot_log_sink()
    driver = nonebot.get_driver()
    driver.register_adapter(ONEBOT_V11Adapter)
    register_onebot_v11_custom_events()
    install_pg_shutdown_hook()

    @driver.on_startup
    async def startup() -> None:
        logger.info("[初始化] 运行服务初始化中...")
        await init_db()
        await start_ban_gate_snapshot()
        schedule_ensure_voices()
        from pallas.core.platform.multi_bot.connected_roster import install_shutdown_signal_forwarder

        install_shutdown_signal_forwarder()

    @driver.on_shutdown
    async def shutdown() -> None:
        from pallas.core.platform.multi_bot.connected_roster import mark_process_shutting_down

        mark_process_shutting_down()
        await stop_ban_gate_snapshot()

    logger.info("[初始化] 模块载入中...")
    load_plugins_for_role()

    @driver.on_startup
    async def emit_startup_summary_on_startup() -> None:
        emit_startup_summary()

    return driver
