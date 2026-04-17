import asyncio
import re
import time
from collections import defaultdict, deque
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from functools import cached_property
from typing import cast

import pypinyin
from nonebot import get_plugin_config
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message

from src.common.config import BotConfig
from src.common.db import Message as MessageModel
from src.common.db import make_context_repository

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


context_repo = make_context_repository()


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
        from .speaker import Speaker

        return await Speaker.speak(Chat._reply_dict, Chat._reply_lock, Chat._recent_topics, Chat._topics_lock)

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

        await context_repo.delete_expired(expiration, Chat.ANSWER_THRESHOLD)

        all_context = await context_repo.find_for_cleanup(100, expiration)
        for context in all_context:
            answers = [ans for ans in context.answers if ans.count > 1 or ans.time > expiration]
            # 使用 replace_answers 细粒度 API，便于拆表后只写 answer 子表 + 更新 clear_time
            await context_repo.replace_answers(context.keywords, answers, cur_time)

    @staticmethod
    async def sync():
        await MessageStore._sync()
        await BanManager._sync_blacklist()
