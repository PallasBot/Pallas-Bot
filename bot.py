from src.foundation.config.dotenv import apply_repo_settings_to_environ

apply_repo_settings_to_environ()

# ruff: noqa: E402
import nonebot
from nonebot.adapters.onebot.v11 import Adapter as ONEBOT_V11Adapter
from nonebot.log import logger

from src.console.web import install_nonebot_log_sink
from src.features.ban_gate import start_ban_gate_snapshot, stop_ban_gate_snapshot
from src.features.message_scrub import start_message_scrub_if_enabled
from src.foundation.db import init_db
from src.foundation.logging import apply_stdlib_logging_channel_prefix, resolve_repo_log_level
from src.foundation.paths import plugin_data_dir
from src.platform.bot_runtime import load_plugins_for_role
from src.shared.adapters import register_onebot_v11_custom_events
from src.shared.utils.voice_downloader import ensure_voices

apply_stdlib_logging_channel_prefix()
file_log_level = resolve_repo_log_level()
nonebot.init()
bot_log_dir = plugin_data_dir("bot", create=True)
logger.add(
    bot_log_dir / "nonebot_{time:YYYY-MM-DD_HH-mm-ss_SSSSSS}.log",
    level=file_log_level,
    rotation="50 MB",
    retention="14 days",
    encoding="utf-8",
    enqueue=True,
)
logger.info("bot file log dir: {} level={}", bot_log_dir, file_log_level)
start_message_scrub_if_enabled()
from src.features.llm.startup_probe import install_llm_startup_probe

install_llm_startup_probe()
install_nonebot_log_sink()
driver = nonebot.get_driver()
driver.register_adapter(ONEBOT_V11Adapter)
register_onebot_v11_custom_events()
config = driver.config


@driver.on_startup
async def startup():
    await init_db()
    await start_ban_gate_snapshot()
    await ensure_voices()


@driver.on_shutdown
async def shutdown():
    await stop_ban_gate_snapshot()


load_plugins_for_role()

if __name__ == "__main__":
    nonebot.run()
