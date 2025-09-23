import nonebot
from nonebot.adapters.milky import Adapter

from src.common.db import init_db
from src.common.utils.voice_downloader import ensure_voices

nonebot.init()

driver = nonebot.get_driver()
driver.register_adapter(Adapter)
config = driver.config


@driver.on_startup
async def startup():
    await init_db(config.mongo_host, config.mongo_port, config.mongo_user, config.mongo_password)

    await ensure_voices()


nonebot.load_from_toml("pyproject.toml")

if __name__ == "__main__":
    nonebot.run()
