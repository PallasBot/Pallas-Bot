import asyncio
import random
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from nonebot import logger

from pallas.core.foundation.db import Message as MessageModel
from pallas.core.foundation.db import make_message_repository
from pallas.core.platform.shard import context as shard_ctx

from .config import get_repeater_config

if TYPE_CHECKING:
    from .model import ChatData


plugin_config = get_repeater_config()


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
    _synced_prefix_counts: dict[int, int] = {}
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
            group_msgs = MessageStore._message_dict[group_id]
            if not group_msgs:
                MessageStore._synced_prefix_counts[group_id] = 0
            group_msgs.append(
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

        # topics 回调可能较慢，放在锁外执行
        if trigger_keywords is not None and topics_callback is not None:
            await topics_callback(group_id, trigger_keywords)

        if should_sync:
            await MessageStore._sync(cur_time)

        if shard_ctx.sharding_active():
            from pallas.core.platform.shard.coord.repeater_buffer import schedule_publish_repeater_buffer

            schedule_publish_repeater_buffer(chat_data)

    @staticmethod
    async def _sync(cur_time: int | None = None):
        """
        持久化：按身份标记待同步消息，bulk_insert 成功后仅移除
        这些消息，避免把同步期间新到达的未同步消息截断丢弃。
        """
        if cur_time is None:
            cur_time = int(time.time())

        async with MessageStore._message_lock:
            if MessageStore._late_save_time == 0:
                MessageStore._synced_prefix_counts.clear()
            save_list: list[MessageModel] = [
                msg
                for group_id, group_msgs in MessageStore._message_dict.items()
                for msg in group_msgs[min(MessageStore._synced_prefix_counts.get(group_id, 0), len(group_msgs)) :]
            ]
            if not save_list:
                return
            sync_boundaries = {
                group_id: len(group_msgs)
                for group_id, group_msgs in MessageStore._message_dict.items()
                if len(group_msgs) > min(MessageStore._synced_prefix_counts.get(group_id, 0), len(group_msgs))
            }

        try:
            await message_repo.bulk_insert(save_list)
        except RuntimeError:
            return
        except Exception as e:
            logger.error(f"repeater message_store bulk_insert failed in _sync: {e}")
            return

        async with MessageStore._message_lock:
            # 仅丢弃本轮真正已同步的消息，
            # 已同步的消息保留最后 SAVE_RESERVED_SIZE 条供随机采样，
            # 未同步的新消息全部保留，留给下一轮 _sync
            new_dict: dict[int, list[MessageModel]] = {}
            new_synced_prefix_counts: dict[int, int] = {}
            for group_id, group_msgs in MessageStore._message_dict.items():
                prior_synced_prefix = min(MessageStore._synced_prefix_counts.get(group_id, 0), len(group_msgs))
                sync_boundary = min(sync_boundaries.get(group_id, prior_synced_prefix), len(group_msgs))
                synced = group_msgs[:sync_boundary]
                unsynced = group_msgs[sync_boundary:]
                if len(synced) > MessageStore.SAVE_RESERVED_SIZE:
                    synced = synced[-MessageStore.SAVE_RESERVED_SIZE :]
                combined = synced + unsynced
                if not combined:
                    continue
                new_dict[group_id] = combined
                new_synced_prefix_counts[group_id] = len(synced)
            MessageStore._message_dict.clear()
            MessageStore._message_dict.update(new_dict)
            MessageStore._synced_prefix_counts = new_synced_prefix_counts

            MessageStore._late_save_time = cur_time

    @staticmethod
    async def periodic_sync_if_buffered() -> bool:
        async with MessageStore._message_lock:
            has_buffered = any(group_msgs for group_msgs in MessageStore._message_dict.values())
        if not has_buffered:
            return False
        await MessageStore._sync()
        return True

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
