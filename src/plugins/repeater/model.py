import asyncio
import random
import re
import time
from collections import defaultdict, deque
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from functools import cached_property, cmp_to_key
from typing import cast

import pypinyin
from beanie.operators import Or
from nonebot import get_plugin_config
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message

from src.common.config import BotConfig
from src.common.db import Context
from src.common.db import Message as MessageModel

from .ban_manager import BanManager
from .config import Config
from .learner import Learner
from .message_store import MessageStore
from .responder import Responder

try:
    import jieba_next.analyse as jieba_analyse

    print("Using jieba_next for repeater")
except ImportError:
    import jieba.analyse as jieba_analyse

    print("Using jieba for repeater")


plugin_config = get_plugin_config(Config)


@dataclass
class ChatData:
    group_id: int
    user_id: int
    raw_message: str
    plain_text: str
    time: int
    bot_id: int

    _keywords_size: int = 2

    @cached_property
    def is_plain_text(self) -> bool:
        return "[CQ:" not in self.raw_message and len(self.plain_text) != 0

    @cached_property
    def is_image(self) -> bool:
        return "[CQ:image," in self.raw_message or "[CQ:face," in self.raw_message

    @cached_property
    def _keywords_list(self) -> list[str]:
        if not self.is_plain_text and len(self.plain_text) == 0:
            return []

        result = jieba_analyse.extract_tags(self.plain_text, topK=ChatData._keywords_size)
        return cast("list[str]", result)  # type: ignore[return-value]

    @cached_property
    def keywords_len(self) -> int:
        return len(self._keywords_list)

    @cached_property
    def keywords(self) -> str:
        if not self.is_plain_text and len(self.plain_text) == 0:
            return self.raw_message

        if self.keywords_len == 0:
            return self.plain_text
        else:
            # keywords_list.sort()
            return " ".join(self._keywords_list)  # type: ignore

    @cached_property
    def keywords_pinyin(self) -> str:
        return "".join([
            item[0] for item in pypinyin.pinyin(self.keywords, style=pypinyin.NORMAL, errors="default")
        ]).lower()

    @cached_property
    def to_me(self) -> bool:
        return self.plain_text.startswith("牛牛")


class Chat:
    # 可以试着改改的参数

    ANSWER_THRESHOLD = plugin_config.answer_threshold
    ANSWER_THRESHOLD_WEIGHTS = plugin_config.answer_threshold_weights
    TOPICS_SIZE = plugin_config.topics_size
    TOPICS_IMPORTANCE = plugin_config.topics_importance
    CROSS_GROUP_THRESHOLD = plugin_config.cross_group_threshold
    REPEAT_THRESHOLD = plugin_config.repeat_threshold
    SPEAK_THRESHOLD = plugin_config.speak_threshold
    DUPLICATE_REPLY = plugin_config.duplicate_reply

    SPLIT_PROBABILITY = plugin_config.split_probability
    DRUNK_TTS_THRESHOLD = plugin_config.drunk_tts_threshold
    SPEAK_CONTINUOUSLY_PROBABILITY = plugin_config.speak_continuously_probability
    SPEAK_POKE_PROBABILITY = plugin_config.speak_poke_probability
    SPEAK_CONTINUOUSLY_MAX_LEN = plugin_config.speak_continuously_max_len

    SAVE_TIME_THRESHOLD = plugin_config.save_time_threshold
    SAVE_COUNT_THRESHOLD = plugin_config.save_count_threshold
    SAVE_RESERVED_SIZE = plugin_config.save_reserved_size

    # 最好别动的参数

    ANSWER_THRESHOLD_CHOICE_LIST = list(
        range(ANSWER_THRESHOLD - len(ANSWER_THRESHOLD_WEIGHTS) + 1, ANSWER_THRESHOLD + 1)
    )
    BLACKLIST_FLAG = 114514
    SPEAK_FLAG = "[PallasBot: Speak]"
    REPLY_FLAG = "[PallasBot: Reply]"

    # 运行期变量

    _reply_dict = defaultdict(lambda: defaultdict(list))  # 牛牛回复的消息缓存，暂未做持久化

    _reply_lock = asyncio.Lock()  # 回复消息缓存锁
    _topics_lock = asyncio.Lock()

    _recent_topics = defaultdict(lambda: deque(maxlen=Chat.TOPICS_SIZE))
    _recent_speak = defaultdict(lambda: deque(maxlen=Chat.DUPLICATE_REPLY))  # 主动发言记录，避免重复内容

    ###

    def __init__(self, data: ChatData | GroupMessageEvent):
        if isinstance(data, ChatData):
            self.chat_data = data
            self.config = BotConfig(data.bot_id, data.group_id)
        elif isinstance(data, GroupMessageEvent):
            self.chat_data = ChatData(
                group_id=data.group_id,
                user_id=data.user_id,
                # 删除图片子类型字段，同一张图子类型经常不一样，影响判断
                raw_message=re.sub(r"\.image,.+?\]", ".image]", data.raw_message),
                plain_text=data.get_plaintext(),
                time=data.time,
                bot_id=data.self_id,
            )
            self.config = BotConfig(data.self_id, data.group_id)

    async def learn(self) -> bool:
        """
        学习这句话
        """
        return await Learner.learn(self.chat_data, Chat._topics_lock, Chat._recent_topics)

    async def answer(self) -> AsyncGenerator[Message, None] | None:
        return await Responder.answer(
            self.chat_data,
            self.config,
            Chat._reply_dict,
            Chat._reply_lock,
            Chat._recent_topics,
            Chat._topics_lock,
        )

    @staticmethod
    async def reply_post_proc(raw_message: str, new_msg: str, bot_id: int, group_id: int) -> bool:
        return await Responder.reply_post_proc(
            raw_message,
            new_msg,
            bot_id,
            group_id,
            Chat._reply_dict,
            Chat._reply_lock,
        )

    @staticmethod
    async def speak() -> tuple[int, int, list[Message], int | None] | None:
        """
        主动发言，返回当前最希望发言的 bot 账号、群号、发言消息 List、戳一戳目标，也有可能不发言
        """

        basic_msgs_len = 10
        basic_delay = 600

        def group_popularity_cmp(lhs: tuple[int, list[MessageModel]], rhs: tuple[int, list[MessageModel]]) -> int:
            def cmp(a: int | float, b: int | float) -> int:
                return (a > b) - (a < b)

            lhs_group_id, lhs_msgs = lhs
            rhs_group_id, rhs_msgs = rhs

            lhs_len = len(lhs_msgs)
            rhs_len = len(rhs_msgs)

            if lhs_len < basic_msgs_len or rhs_len < basic_msgs_len:
                return cmp(lhs_len, rhs_len)

            lhs_duration = lhs_msgs[-1].time - lhs_msgs[0].time
            rhs_duration = rhs_msgs[-1].time - rhs_msgs[0].time

            if not lhs_duration or not rhs_duration:
                return cmp(lhs_len, rhs_len)

            return cmp(lhs_len / lhs_duration, rhs_len / rhs_duration)

        # 按群聊热度排序
        popularity = sorted(MessageStore._message_dict.items(), key=cmp_to_key(group_popularity_cmp))

        cur_time = time.time()
        for group_id, group_msgs in popularity:
            group_replies = Chat._reply_dict[group_id]
            if not len(group_replies) or len(group_msgs) < basic_msgs_len:
                continue

            # 一般来说所有牛牛都是一起回复的，最后发言时间应该是一样的，随意随便选一个[0]就好了
            group_replies_front = list(group_replies.values())[0]
            if not len(group_replies_front) or group_replies_front[-1]["time"] > group_msgs[-1].time:
                continue

            msgs_len = len(group_msgs)
            latest_time = group_msgs[-1].time
            duration = latest_time - group_msgs[0].time
            avg_interval = duration / msgs_len

            # 已经超过平均发言间隔 N 倍的时间没有人说话了，才主动发言
            if cur_time - latest_time < avg_interval * Chat.SPEAK_THRESHOLD + basic_delay:
                continue

            # append 一个 flag, 防止这个群热度特别高，但压根就没有可用的 context 时，每次 speak 都查这个群，浪费时间
            async with Chat._reply_lock:
                group_replies_front.append({
                    "time": int(cur_time),
                    "pre_raw_message": Chat.SPEAK_FLAG,
                    "pre_keywords": Chat.SPEAK_FLAG,
                    "reply": Chat.SPEAK_FLAG,
                    "reply_keywords": Chat.SPEAK_FLAG,
                })

            bot_id = random.choice([bid for bid in group_replies.keys() if bid])

            ban_keywords = await BanManager.find_ban_keywords(context=None, group_id=group_id)

            recently = Chat._recent_speak[group_id]

            def msg_filter(msg: MessageModel) -> bool:
                cur_raw_message = msg.raw_message
                cur_keywords = msg.keywords
                return (
                    cur_keywords not in ban_keywords  # noqa: B023
                    and cur_raw_message not in recently  # noqa: B023
                    and not cur_raw_message.startswith("牛牛")
                    and not cur_raw_message.startswith("[CQ:xml")
                    and "\n" not in cur_raw_message
                )

            available_messages = list(filter(msg_filter, MessageStore._message_dict[group_id]))
            if not available_messages:
                continue

            taken_name = await BotConfig(bot_id, group_id).taken_name()
            pretend_msg = list(filter(lambda msg: msg.user_id == taken_name, available_messages))
            first_message = pretend_msg[0] if pretend_msg else available_messages[0]
            speak = first_message.raw_message
            Chat._recent_speak[group_id].append(speak)

            async with Chat._reply_lock:
                group_replies[bot_id].append({
                    "time": int(cur_time),
                    "pre_raw_message": Chat.SPEAK_FLAG,
                    "pre_keywords": Chat.SPEAK_FLAG,
                    "reply": speak,
                    "reply_keywords": Chat.SPEAK_FLAG,
                })

            speak_list = [
                Message(speak),
            ]

            while (
                random.random() < Chat.SPEAK_CONTINUOUSLY_PROBABILITY
                and len(speak_list) < Chat.SPEAK_CONTINUOUSLY_MAX_LEN
            ):
                pre_msg = str(speak_list[-1])

                answer_generator = await Chat(ChatData(group_id, 0, pre_msg, pre_msg, int(cur_time), 0)).answer()
                if not answer_generator:
                    break

                new_messages = [msg_item async for msg_item in answer_generator]
                if not new_messages:
                    break

                speak_list.extend(new_messages)

            target_id = None
            if random.random() < Chat.SPEAK_POKE_PROBABILITY:
                target_id = random.choice(MessageStore._message_dict[group_id]).user_id

            return (bot_id, group_id, speak_list, target_id)

        return None

    @staticmethod
    async def ban(group_id: int, bot_id: int, ban_raw_message: str, reason: str) -> bool:
        return await BanManager.ban(group_id, bot_id, ban_raw_message, reason, Chat._reply_dict)

    @staticmethod
    async def get_random_message_from_each_group() -> dict[int, MessageModel]:
        """
        获取每个群近期一条随机发言

        TODO: 随机权重可以改为 keywords 出现频率 或 用户发言频率 正相关
        """

        return await MessageStore.get_random_message_from_each_group()

    @staticmethod
    async def update_global_blacklist() -> None:
        await BanManager.update_global_blacklist()

    @staticmethod
    async def clearup_context() -> None:
        """
        清理所有超过 15 天没人说、且没有学会的话
        """

        cur_time = int(time.time())
        expiration = cur_time - 15 * 24 * 3600  # 15 天前

        await Context.find(Context.time < expiration, Context.trigger_count < Chat.ANSWER_THRESHOLD).delete()

        all_context = await Context.find(Or(Context.trigger_count > 100, Context.clear_time < expiration)).to_list()
        for context in all_context:
            answers = [ans for ans in context.answers if ans.count > 1 or ans.time > expiration]
            context.answers = answers
            context.clear_time = cur_time
            await context.save()

    @staticmethod
    async def sync():
        await MessageStore._sync()
        await BanManager._sync_blacklist()
