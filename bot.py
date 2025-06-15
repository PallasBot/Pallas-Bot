import nonebot
from nonebot.adapters.onebot.v11 import Adapter as ONEBOT_V11Adapter

from src.common.db import init_db
from src.plugins.repeater import Chat

nonebot.init()

driver = nonebot.get_driver()
driver.register_adapter(ONEBOT_V11Adapter)
config = driver.config


@driver.on_startup
async def startup():
    await init_db(config.mongo_host, config.mongo_port)
    await Chat.update_global_blacklist()


@driver.on_shutdown
async def shutdown():
    await Chat.sync()


nonebot.load_from_toml("pyproject.toml")

if __name__ == "__main__":
    nonebot.run()
