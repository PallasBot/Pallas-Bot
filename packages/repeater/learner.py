import asyncio
from collections import deque
from typing import TYPE_CHECKING

from pallas.core.foundation.db import Answer, Context
from pallas.core.foundation.db import Message as MessageModel
from pallas.core.foundation.db.context_repo_access import context_repo

from .context_exists_cache import context_exists_for_learn, note_context_exists
from .learner_context import group_messages_before
from .message_store import MessageStore
from .repeat_teach import is_forced_repeat_teaching
from .topic_utils import filtered_recent_topics

if TYPE_CHECKING:
    from .model import ChatData


class Learner:
    """
    从 Chat 类提取的学习逻辑，负责上下文插入和消息学习
    """

    @staticmethod
    async def learn(
        chat_data: "ChatData",
        topics_lock: asyncio.Lock,
        recent_topics: dict[int, deque],
    ) -> bool:
        """
        学习这句话
        """

        if len(chat_data.raw_message.strip()) == 0:
            return False

        from .responder import Responder

        if chat_data.user_id in Responder._repeat_ignore_user_ids():
            return False

        from pallas.core.plugin_coord.duel import should_skip_repeater_learn

        if await should_skip_repeater_learn(chat_data.group_id, chat_data.user_id, chat_data.raw_message):
            return False

        group_msgs = await group_messages_before(chat_data)
        if is_forced_repeat_teaching(chat_data, group_msgs):
            from pallas.product.persona.group_style_refresh import mark_group_style_forced_teach

            mark_group_style_forced_teach(chat_data.group_id)
        if group_msgs:
            group_pre_msg = group_msgs[-1]
            await Learner._context_insert(chat_data, group_pre_msg)

        async def _topics_callback(group_id: int, keywords_list: list[str]):
            async with topics_lock:
                recent_topics[group_id] += filtered_recent_topics(keywords_list)

        await MessageStore.message_insert(chat_data, topics_callback=_topics_callback)
        from pallas.product.persona.group_style_refresh import mark_group_style_dirty

        mark_group_style_dirty(chat_data.group_id)
        return True

    @staticmethod
    async def _context_insert(chat_data: "ChatData", pre_msg: MessageModel | None):
        """
        插入上下文关联：将前一条消息与当前消息建立学习关系
        """
        if not pre_msg:
            return

        raw_message = chat_data.raw_message

        # 在复读，不学
        if pre_msg.raw_message == raw_message:
            return

        # 回复别人的，不学
        if "[CQ:reply," in raw_message:
            return

        keywords = chat_data.keywords
        group_id = chat_data.group_id
        pre_keywords = pre_msg.keywords
        cur_time = chat_data.time

        learn_answer = getattr(context_repo, "learn_answer", None)
        if callable(learn_answer):
            await learn_answer(
                keywords=pre_keywords,
                group_id=group_id,
                answer_keywords=keywords,
                answer_time=cur_time,
                message=raw_message,
                append_on_existing=chat_data.is_plain_text,
            )
            await note_context_exists(pre_keywords)
            return

        if await context_exists_for_learn(pre_keywords):
            # 使用细粒度 upsert_answer：原子地 inc count / set time / 可选 push message
            # append_on_existing 保留原有 "仅 plain text 才追加 message" 的语义
            await context_repo.upsert_answer(
                keywords=pre_keywords,
                group_id=group_id,
                answer_keywords=keywords,
                answer_time=cur_time,
                message=raw_message,
                append_on_existing=chat_data.is_plain_text,
            )
            await note_context_exists(pre_keywords)
        else:
            context = Context.model_construct(
                keywords=pre_keywords,
                time=cur_time,
                trigger_count=1,
                answers=[Answer(keywords=keywords, group_id=group_id, count=1, time=cur_time, messages=[raw_message])],
                ban=[],
                clear_time=0,
            )
            await context_repo.insert(context)
            await note_context_exists(pre_keywords)
