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
        cur_time = chat_data.time

        should_sync = False
        trigger_keywords: list[str] | None = None

        async with MessageStore._message_lock:
            MessageStore._message_dict[group_id].append(
                MessageModel.model_construct(
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

            if chat_data.is_plain_text and topics_callback is not None:
                trigger_keywords = chat_data._keywords_list

            # 阈值判断与 _late_save_time 更新必须与 append 处于同一把锁下，
            # 否则并发插入可能同时看到跨阈值 / 同时触发 _sync
            if MessageStore._late_save_time == 0:
                MessageStore._late_save_time = cur_time - 1
            else:
                count = len(MessageStore._message_dict[group_id])
                if (
                    count > MessageStore.SAVE_COUNT_THRESHOLD
                    or cur_time - MessageStore._late_save_time > MessageStore.SAVE_TIME_THRESHOLD
                ):
                    should_sync = True

        # topics 回调可能较慢（含 IO），放在锁外执行
        if trigger_keywords is not None and topics_callback is not None:
            await topics_callback(group_id, trigger_keywords)

        if should_sync:
            await MessageStore._sync(cur_time)

    @staticmethod
    async def _sync(cur_time: int | None = None):
        """
        持久化：按身份（id(msg)）标记待同步消息，bulk_insert 成功后仅移除
        这些消息，避免把同步期间新到达的未同步消息截断丢弃。
        """
        if cur_time is None:
            cur_time = int(time.time())

        async with MessageStore._message_lock:
            save_list: list[MessageModel] = [
                msg
                for group_msgs in MessageStore._message_dict.values()
                for msg in group_msgs
                if msg.time > MessageStore._late_save_time
            ]
            if not save_list:
                return
            syncing_ids = {id(msg) for msg in save_list}

        try:
            await message_repo.bulk_insert(save_list)
        except RuntimeError:
            return
        except Exception as e:
            logger.error(f"Failed to insert messages in _sync: {e}")
            return

        async with MessageStore._message_lock:
            # 仅丢弃本轮真正已同步的消息（按 id 判定），
            # 已同步的消息保留最后 SAVE_RESERVED_SIZE 条供随机采样，
            # 未同步的新消息全部保留，留给下一轮 _sync
            new_dict: dict[int, list[MessageModel]] = {}
            for group_id, group_msgs in MessageStore._message_dict.items():
                synced: list[MessageModel] = []
                unsynced: list[MessageModel] = []
                for msg in group_msgs:
                    if id(msg) in syncing_ids:
                        synced.append(msg)
                    else:
                        unsynced.append(msg)
                if len(synced) > MessageStore.SAVE_RESERVED_SIZE:
                    synced = synced[-MessageStore.SAVE_RESERVED_SIZE :]
                new_dict[group_id] = synced + unsynced
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
