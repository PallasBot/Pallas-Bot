from src.common.config.dotenv import apply_repo_settings_to_environ

apply_repo_settings_to_environ()

# ruff: noqa: E402
import nonebot
from nonebot.adapters.onebot.v11 import Adapter as ONEBOT_V11Adapter

from src.common.ban_gate import start_ban_gate_snapshot, stop_ban_gate_snapshot
from src.common.bot_runtime import load_plugins_for_role
from src.common.db import init_db
from src.common.logging import apply_stdlib_logging_channel_prefix
from src.common.utils.voice_downloader import ensure_voices
from src.common.web import install_nonebot_log_sink

apply_stdlib_logging_channel_prefix()
nonebot.init()
install_nonebot_log_sink()
driver = nonebot.get_driver()
driver.register_adapter(ONEBOT_V11Adapter)
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
