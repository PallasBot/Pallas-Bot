import asyncio
from datetime import datetime, timedelta

from nonebot import get_bots, logger
from nonebot.adapters.milky import Bot
from nonebot_plugin_apscheduler import scheduler

from src.plugins.block import plugin_config as block_config

from .config import plugin_config

offline_bots: dict[int, dict[str, str]] = {}

STATUS_COOLDOWN_KEY: str = "bot_status"


async def get_bot_nickname(bot_id: int, current_bots: dict = None) -> str:
    """获取牛牛昵称"""
    nickname: str = "Unknown Nickname"
    try:
        bots = current_bots if current_bots is not None else get_bots()

        # 首先尝试让牛牛自己获取自己的信息
        if str(bot_id) in bots:
            try:
                info = await bots[str(bot_id)].call_api("get_stranger_info", user_id=bot_id)
                nickname = info.get("nickname", "Unknown Nickname")
                if nickname != "Unknown Nickname":
                    return nickname
            except Exception as e:
                logger.debug(f"Failed to get bot {bot_id} info using itself: {e}")

        available_bots = [bot_instance for bot_id_key, bot_instance in bots.items() if int(bot_id_key) != bot_id]

        max_retries = 3
        for attempt in range(max_retries):
            if attempt > 0:
                logger.debug(f"Retrying ({attempt + 1}/{max_retries}) to get nickname for bot {bot_id}")

            for bot_instance in available_bots:
                try:
                    info = await bot_instance.call_api("get_stranger_info", user_id=bot_id)
                    nickname = info.get("nickname", "Unknown Nickname")
                    if nickname != "Unknown Nickname":
                        return nickname
                except Exception as e:
                    logger.debug(
                        f"Attempt {attempt + 1}: Failed to get bot {bot_id} info using bot {bot_instance.self_id}: {e}"
                    )
                    continue

            if attempt < max_retries - 1:
                await asyncio.sleep(0.1)

    except Exception as e:
        logger.debug(f"Failed to get nickname for bot {bot_id}: {e}")

    return nickname


async def handle_bot_connect(bot: Bot) -> None:
    bot_id: int = int(bot.self_id)
    if bot_id in offline_bots:
        del offline_bots[bot_id]


async def handle_bot_disconnect(bot: Bot) -> None:
    bot_id: int = int(bot.self_id)
    if bot_id in offline_bots and "source" in offline_bots[bot_id]:
        # 已经处理过了，直接返回
        return

    nickname: str = await get_bot_nickname(bot_id)

    offline_bots[bot_id] = {
        "nickname": nickname,
        "offline_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": "disconnect_event",
    }

    job_id: str = f"bot_status_check_{bot_id}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)

    # 计算运行时间
    run_time: datetime = datetime.now() + timedelta(seconds=plugin_config.bot_status_offline_grace_time)

    scheduler.add_job(
        id=job_id,
        func=check_bot_still_offline,
        args=[
            bot_id,
            nickname,
        ],
        misfire_grace_time=60,
        coalesce=True,
        max_instances=1,
        trigger="date",
        run_date=run_time,
    )


async def check_bot_still_offline(bot_id: int, nickname: str) -> None:
    """检查牛牛是否真的离线"""
    bots = get_bots()
    if str(bot_id) not in bots:
        logger.warning(f"Bot {bot_id} offline, sending notification")
        # 更新离线时间
        if bot_id in offline_bots:
            offline_bots[bot_id]["offline_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        else:
            # 如果不在离线列表中，则添加进去
            offline_bots[bot_id] = {
                "nickname": nickname,
                "offline_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "source": "checked_offline",
            }
        # 发送离线通知
        try:
            from .mail_notifier import notify_bot_offline

            await notify_bot_offline(bot_id, nickname)
        except Exception as e:
            logger.error(f"Failed to send offline notification for bot {bot_id}: {e}")
    else:
        # 牛牛实际上在线，从离线列表中删除
        if (
            bot_id in offline_bots
            and "source" in offline_bots[bot_id]
            and offline_bots[bot_id]["source"] == "checked_offline"
        ):
            del offline_bots[bot_id]
        elif bot_id in offline_bots and "source" not in offline_bots[bot_id]:
            pass


async def get_bot_status_info() -> tuple[dict[int, str], dict[int, str]]:
    """获取牛牛状态信息"""
    # 获取当前在线的牛牛
    current_bots = get_bots()

    all_bot_ids = set(block_config.bots) if block_config.bots else set()

    if not all_bot_ids:
        all_bot_ids.update(int(bot_id) for bot_id in current_bots.keys())

    all_bot_ids.update(offline_bots.keys())

    async def get_nickname_with_status(bot_id: int) -> tuple[int, str, bool]:
        """获取昵称和在线状态任务"""
        if str(bot_id) in current_bots:
            nickname = await get_bot_nickname(bot_id, current_bots)
            return bot_id, nickname, True  # 在线
        else:
            nickname = await get_bot_nickname(bot_id)
            # 更新offline_bots中的昵称信息
            if bot_id in offline_bots:
                offline_bots[bot_id]["nickname"] = nickname
            return bot_id, nickname, False  # 离线

    bot_info_tasks = [get_nickname_with_status(bot_id) for bot_id in all_bot_ids]
    bot_info_results = await asyncio.gather(*bot_info_tasks, return_exceptions=True)

    online_bots: dict[int, str] = {}
    offline_bots_filtered: dict[int, str] = {}

    for result in bot_info_results:
        if isinstance(result, Exception):
            logger.warning(f"Error occurred while getting bot info: {result}")
            continue

        bot_id, nickname, is_online = result
        if is_online:
            online_bots[bot_id] = nickname
            # 如果这个Bot之前在离线列表中，更新其昵称
            if bot_id in offline_bots:
                offline_bots[bot_id]["nickname"] = nickname
        else:
            offline_bots_filtered[bot_id] = nickname

    return online_bots, offline_bots_filtered
