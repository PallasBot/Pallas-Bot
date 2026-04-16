import asyncio
import random
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from nonebot import get_plugin_config, logger

from src.common.db import Message as MessageModel
from src.common.db import make_message_repository

from .config import Config

if TYPE_CHECKING:
    from .model import ChatData


plugin_config = get_plugin_config(Config)


message_repo = make_message_repository()


class MessageStore:
    """
    消息存储与持久化层，负责消息缓存、数据库同步和检索
    """

    # Constants
    SAVE_TIME_THRESHOLD = plugin_config.save_time_threshold
    SAVE_COUNT_THRESHOLD = plugin_config.save_count_threshold
    SAVE_RESERVED_SIZE = plugin_config.save_reserved_size

    # Class variables
    _message_dict: dict[int, list[MessageModel]] = defaultdict(list)
    _message_lock = asyncio.Lock()
    _late_save_time = 0

    @staticmethod
    async def message_insert(
        chat_data: "ChatData", topics_callback: Callable[[int, list[str]], Awaitable[None]] | None = None
    ):
        """
        将消息插入缓存，达到阈值时触发持久化
        """
        group_id = chat_data.group_id

        async with MessageStore._message_lock:
            MessageStore._message_dict[group_id].append(
                MessageModel(
                    group_id=group_id,
                    user_id=chat_data.user_id,
                    bot_id=chat_data.bot_id,
                    raw_message=chat_data.raw_message,
                    is_plain_text=chat_data.is_plain_text,
                    plain_text=chat_data.plain_text,
                    keywords=chat_data.keywords,
                    time=chat_data.time,
                )
            )

        # 纯文本消息时调用 topics 回调
        if chat_data.is_plain_text and topics_callback:
            await topics_callback(group_id, chat_data._keywords_list)

        cur_time = chat_data.time
        if MessageStore._late_save_time == 0:
            MessageStore._late_save_time = cur_time - 1
            return

        if len(MessageStore._message_dict[group_id]) > MessageStore.SAVE_COUNT_THRESHOLD:
            await MessageStore._sync(cur_time)

        elif cur_time - MessageStore._late_save_time > MessageStore.SAVE_TIME_THRESHOLD:
            await MessageStore._sync(cur_time)

    @staticmethod
    async def _sync(cur_time: int | None = None):
        """
        持久化
        """
        if cur_time is None:
            cur_time = int(time.time())

        # 步骤 1: 收集待保存列表，暂不清空 _message_dict
        async with MessageStore._message_lock:
            save_list = [
                msg
                for group_msgs in MessageStore._message_dict.values()
                for msg in group_msgs
                if msg.time > MessageStore._late_save_time
            ]
            if not save_list:
                return

        # 步骤 2: 在锁外执行 insert_many
        try:
            await message_repo.bulk_insert(save_list)
        except Exception as e:
            # 插入失败时记录错误并保留数据，避免丢失
            logger.error(f"Failed to insert messages in _sync: {e}")
            return

        # 步骤 3: 插入成功后才截断并更新 _late_save_time
        async with MessageStore._message_lock:
            new_dict = {
                group_id: group_msgs[-MessageStore.SAVE_RESERVED_SIZE :]
                for group_id, group_msgs in MessageStore._message_dict.items()
            }
            MessageStore._message_dict.clear()
            MessageStore._message_dict.update(new_dict)

            MessageStore._late_save_time = cur_time

    @staticmethod
    async def get_random_message_from_each_group() -> dict[int, MessageModel]:
        """
        获取每个群近期一条随机发言

        TODO: 随机权重可以改为 keywords 出现频率 或 用户发言频率 正相关
        """

        return {
            group_id: random.choice(group_msgs)
            for group_id, group_msgs in MessageStore._message_dict.items()
            if group_msgs
        }
