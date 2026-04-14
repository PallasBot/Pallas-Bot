import asyncio
import random
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from nonebot import get_plugin_config, logger

from src.common.db import Message as MessageModel
from src.common.db.repository_impl import MongoMessageRepository

from .config import Config

if TYPE_CHECKING:
    from .model import ChatData


plugin_config = get_plugin_config(Config)


_message_repo = MongoMessageRepository()


class MessageStore:
    """
    Message storage and persistence layer for Chat plugin.
    Handles message caching, synchronization to database, and retrieval.
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
        Insert a message into the message cache and optionally trigger persistence.

        Args:
            chat_data: The chat data to insert
            topics_callback: Optional callback to update topics, called with (group_id, keywords_list)
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

        # Call topics callback if provided and message is plain text
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
    async def _sync(cur_time: int = int(time.time())):
        """
        持久化
        """

        # Step 1: Collect save_list without clearing _message_dict yet
        async with MessageStore._message_lock:
            save_list = [
                msg
                for group_msgs in MessageStore._message_dict.values()
                for msg in group_msgs
                if msg.time > MessageStore._late_save_time
            ]
            if not save_list:
                return

        # Step 2: Call insert_many OUTSIDE the lock
        try:
            await _message_repo.bulk_insert(save_list)
        except Exception as e:
            # Step 4: If insert_many fails, log error and preserve data
            logger.error(f"Failed to insert messages in _sync: {e}")
            return

        # Step 3: Only truncate and update _late_save_time if insert_many succeeded
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
