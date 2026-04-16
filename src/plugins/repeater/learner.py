import asyncio
from collections import deque
from typing import TYPE_CHECKING

from src.common.db import Answer, Context, make_context_repository
from src.common.db import Message as MessageModel

from .message_store import MessageStore

if TYPE_CHECKING:
    from .model import ChatData


context_repo = make_context_repository()


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

        group_id = chat_data.group_id
        if group_id in MessageStore._message_dict:
            group_msgs = MessageStore._message_dict[group_id]
            if group_msgs:
                group_pre_msg = group_msgs[-1]
            else:
                group_pre_msg = None

            # 群里的上一条发言
            await Learner._context_insert(chat_data, group_pre_msg)

            user_id = chat_data.user_id
            if group_pre_msg and group_pre_msg.user_id != user_id:
                # 该用户在群里的上一条发言（倒序三句之内）
                for msg in group_msgs[:-3:-1]:
                    if msg.user_id == user_id:
                        await Learner._context_insert(chat_data, msg)
                        break

        async def _topics_callback(group_id: int, keywords_list: list[str]):
            async with topics_lock:
                recent_topics[group_id] += [k for k in keywords_list if not k.startswith("牛牛")]

        await MessageStore.message_insert(chat_data, topics_callback=_topics_callback)
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

        context = await context_repo.find_by_keywords(pre_keywords)
        if context:
            answer_index = next(
                (
                    idx
                    for idx, answer in enumerate(context.answers)
                    if answer.group_id == group_id and answer.keywords == keywords
                ),
                -1,
            )
            if answer_index != -1:
                context.answers[answer_index].count += 1
                context.answers[answer_index].time = cur_time
                if chat_data.is_plain_text:
                    context.answers[answer_index].messages.append(raw_message)
            else:
                context.answers.append(
                    Answer(keywords=keywords, group_id=group_id, count=1, time=cur_time, messages=[raw_message])
                )
            context.time = cur_time
            context.trigger_count += 1
            await context_repo.save(context)

        else:
            context = Context(
                keywords=pre_keywords,
                time=cur_time,
                trigger_count=1,  # type: ignore
                answers=[Answer(keywords=keywords, group_id=group_id, count=1, time=cur_time, messages=[raw_message])],
            )
            await context_repo.insert(context)
