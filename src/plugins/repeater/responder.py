import random
import time
from collections import defaultdict
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING

from nonebot import get_plugin_config
from nonebot.adapters.onebot.v11 import Message

from src.common.config import BotConfig
from src.common.db import Answer
from src.common.db.repository_impl import MongoContextRepository

from .ban_manager import BanManager
from .config import Config

if TYPE_CHECKING:
    from .model import ChatData


plugin_config = get_plugin_config(Config)


_context_repo = MongoContextRepository()


class Responder:
    ANSWER_THRESHOLD = plugin_config.answer_threshold
    ANSWER_THRESHOLD_WEIGHTS = plugin_config.answer_threshold_weights
    TOPICS_SIZE = plugin_config.topics_size
    TOPICS_IMPORTANCE = plugin_config.topics_importance
    CROSS_GROUP_THRESHOLD = plugin_config.cross_group_threshold
    REPEAT_THRESHOLD = plugin_config.repeat_threshold
    DUPLICATE_REPLY = plugin_config.duplicate_reply

    SPLIT_PROBABILITY = plugin_config.split_probability

    SAVE_RESERVED_SIZE = plugin_config.save_reserved_size

    ANSWER_THRESHOLD_CHOICE_LIST = list(
        range(ANSWER_THRESHOLD - len(ANSWER_THRESHOLD_WEIGHTS) + 1, ANSWER_THRESHOLD + 1)
    )
    BLACKLIST_FLAG = 114514
    REPLY_FLAG = "[PallasBot: Reply]"

    @staticmethod
    async def answer(
        chat_data: "ChatData",
        config: BotConfig,
        reply_dict,
        reply_lock,
        recent_topics,
        topics_lock,
    ) -> AsyncGenerator[Message, None] | None:
        """
        回复这句话，可能会分多次回复，也可能不回复
        """
        # 不回复太短的对话，大部分是“？”、“草”
        if chat_data.is_plain_text and len(chat_data.plain_text) < 2:
            return None

        from .message_store import MessageStore

        results = await Responder._context_find(
            chat_data, config, reply_dict, MessageStore._message_dict, recent_topics
        )
        if not results:
            return None

        group_id = chat_data.group_id
        bot_id = chat_data.bot_id
        group_bot_replies = reply_dict[group_id][bot_id]

        raw_message = chat_data.raw_message
        keywords = chat_data.keywords
        async with reply_lock:
            group_bot_replies.append({
                "time": int(time.time()),
                "pre_raw_message": raw_message,
                "pre_keywords": keywords,
                "reply": Responder.REPLY_FLAG,
                "reply_keywords": Responder.REPLY_FLAG,
            })

        async def yield_results(results: tuple[list[str], str]) -> AsyncGenerator[Message, None]:
            answer_list, answer_keywords = results
            group_bot_replies = reply_dict[group_id][bot_id]
            try:
                for item in answer_list:
                    async with reply_lock:
                        group_bot_replies.append({
                            "time": int(time.time()),
                            "pre_raw_message": raw_message,
                            "pre_keywords": keywords,
                            "reply": item,
                            "reply_keywords": answer_keywords,
                        })
                    if "[CQ:" not in item:
                        async with topics_lock:
                            recent_topics[group_id] += [
                                k for k in answer_keywords.split(" ") if not k.startswith("牛牛")
                            ]
                    async with topics_lock:
                        recent_topics[group_id] += [k for k in chat_data._keywords_list if not k.startswith("牛牛")]
                    # if "[CQ:" not in item and len(item) > Chat.DRUNK_TTS_THRESHOLD and \
                    #    await self.config.drunkenness():
                    #     yield Message(Chat._text_to_speech(item))
                    yield Message(item)
            finally:
                async with reply_lock:
                    reply_dict[group_id][bot_id][:] = reply_dict[group_id][bot_id][-Responder.SAVE_RESERVED_SIZE :]

        return yield_results(results)

    @staticmethod
    async def reply_post_proc(
        raw_message: str, new_msg: str, bot_id: int, group_id: int, reply_dict, reply_lock
    ) -> bool:
        """
        对 bot 回复的消息进行后处理，将缓存替换为处理后的消息
        """

        if raw_message == new_msg:
            return True

        async with reply_lock:
            reply_data = reply_dict[group_id][bot_id][::-1]
            for item in reply_data:
                if item["reply"] == raw_message:
                    item["reply"] = new_msg
                    return True
        return False

    @staticmethod
    async def _context_find(
        chat_data: "ChatData",
        config: BotConfig,
        reply_dict,
        message_dict,
        recent_topics,
    ) -> tuple[list[str], str] | None:
        group_id = chat_data.group_id
        raw_message = chat_data.raw_message
        keywords = chat_data.keywords
        bot_id = chat_data.bot_id

        # 复读！
        if group_id in message_dict:
            group_msgs = message_dict[group_id]
            if len(group_msgs) >= Responder.REPEAT_THRESHOLD and all(
                item.raw_message == raw_message for item in group_msgs[-Responder.REPEAT_THRESHOLD + 1 :]
            ):
                # 到这里说明当前群里是在复读
                group_bot_replies = reply_dict[group_id][bot_id]
                if len(group_bot_replies) and group_bot_replies[-1]["reply"] != raw_message:
                    return (
                        [
                            raw_message,
                        ],
                        keywords,
                    )
                else:
                    # 复读过一次就不再回复这句话了
                    return None

        context = await _context_repo.find_by_keywords(keywords)

        if not context:
            return None

        is_drunk = await config.drunkenness() > 0

        if is_drunk:
            answer_count_threshold = 1
        else:
            answer_count_threshold = random.choices(
                Responder.ANSWER_THRESHOLD_CHOICE_LIST, weights=Responder.ANSWER_THRESHOLD_WEIGHTS
            )[0]
            from .model import ChatData

            if chat_data.keywords_len == ChatData._keywords_size:
                answer_count_threshold -= 1

        if chat_data.to_me:
            cross_group_threshold = 1
        else:
            cross_group_threshold = Responder.CROSS_GROUP_THRESHOLD

        ban_keywords = await BanManager.find_ban_keywords(context=context, group_id=group_id)

        candidate_answers: dict[str, Answer] = {}
        other_group_cache = {}
        answers_count = defaultdict(int)
        recent_replies = [r["reply_keywords"] for r in reply_dict[group_id][bot_id][-Responder.DUPLICATE_REPLY :]]
        recent_message = [m.raw_message for m in message_dict[group_id][-Responder.DUPLICATE_REPLY :]]

        def candidate_append(dst: dict[str, Answer], answer: Answer):
            answer_key = answer.keywords
            if "[CQ:" not in answer_key:
                topics = recent_topics[group_id]
                for key in answer_key.split(" "):
                    if key in topics:
                        answer._topical += topics.count(key)

            if answer_key not in dst:
                dst[answer_key] = answer
            else:
                pre_answer = dst[answer_key]
                pre_answer.count += answer.count
                pre_answer.messages += answer.messages

        for answer in context.answers:
            count = answer.count
            if not is_drunk and count < answer_count_threshold:
                continue

            answer_key = answer.keywords
            if answer_key in ban_keywords or answer_key in recent_replies or answer_key == keywords:
                continue

            sample_msg = answer.messages[0]
            if chat_data.is_image and "[CQ:" not in sample_msg:
                # 图片消息不回复纯文本。图片经常是表情包，后面的纯文本啥都有，很乱
                continue
            if sample_msg.startswith("牛牛"):
                if not chat_data.to_me or len(sample_msg) <= 6:
                    # 这种一般是学反过来的，比如有人教“牛牛你好”——“你好”（反复发了好几次，互为上下文了）
                    # 然后下次有人发“你好”，突然回个“牛牛你好”，有点莫名其妙的
                    continue
            if sample_msg.startswith("[CQ:xml"):
                continue
            if "\n" in sample_msg:
                continue
            if count < 3 and sample_msg in recent_message:  # 别人刚发的就重复，显得很笨
                continue

            if answer.group_id == group_id:
                candidate_append(candidate_answers, answer)
            # 别的群的 at, 忽略
            elif "[CQ:at,qq=" in sample_msg:
                continue
            elif is_drunk and count > answer_count_threshold:
                candidate_append(candidate_answers, answer)
            else:  # 有这么 N 个群都有相同的回复，就作为全局回复
                answers_count[answer_key] += 1
                cur_count = answers_count[answer_key]
                if cur_count < cross_group_threshold:  # 没达到阈值前，先缓存
                    candidate_append(other_group_cache, answer)
                elif cur_count == cross_group_threshold:  # 刚达到阈值时，将缓存加入
                    if cur_count > 1:
                        candidate_append(candidate_answers, other_group_cache[answer_key])
                    candidate_append(candidate_answers, answer)
                else:  # 超过阈值后，加入
                    candidate_append(candidate_answers, answer)

        if not candidate_answers:
            return None

        weights = [
            min(answer.count, 10) + answer._topical * Responder.TOPICS_IMPORTANCE
            for answer in candidate_answers.values()
        ]
        final_answer = random.choices(list(candidate_answers.values()), weights=weights)[0]
        answer_str = random.choice(final_answer.messages)
        answer_keywords = final_answer.keywords
        answer_str = answer_str.removeprefix("牛牛")

        if (
            0 < answer_str.count("，") <= 3
            and "[CQ:" not in answer_str
            and random.random() < Responder.SPLIT_PROBABILITY
        ):
            return (answer_str.split("，"), answer_keywords)
        return (
            [
                answer_str,
            ],
            answer_keywords,
        )
