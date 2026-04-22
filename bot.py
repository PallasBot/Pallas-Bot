import nonebot
from nonebot.adapters.onebot.v11 import Adapter as ONEBOT_V11Adapter

from src.common.db import init_db
from src.common.utils.voice_downloader import ensure_voices

nonebot.init()

driver = nonebot.get_driver()
driver.register_adapter(ONEBOT_V11Adapter)
config = driver.config


@driver.on_startup
async def startup():
    await init_db()

    await ensure_voices()


nonebot.load_from_toml("pyproject.toml")

if __name__ == "__main__":
    nonebot.run()
