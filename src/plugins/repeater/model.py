import asyncio
import random
import re
import time
from collections import defaultdict, deque
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from functools import cached_property, cmp_to_key

import pypinyin
from beanie.operators import Or
from nonebot import get_plugin_config
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message

from src.common.config import BotConfig
from src.common.db import Answer, Ban, Context
from src.common.db import Message as MessageModel
from src.common.db.modules import BlackList

from .config import Config

try:
    import jieba_fast.analyse as jieba_analyse

    print("Using jieba_fast for repeater")
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
    def _keywords_list(self):
        if not self.is_plain_text and len(self.plain_text) == 0:
            return []

        return jieba_analyse.extract_tags(self.plain_text, topK=ChatData._keywords_size)

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
            return " ".join(self._keywords_list)

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
    _message_dict: dict[int, list[MessageModel]] = defaultdict(list)  # 群消息缓存

    _reply_lock = asyncio.Lock()  # 回复消息缓存锁
    _message_lock = asyncio.Lock()
    _topics_lock = asyncio.Lock()

    _late_save_time = 0  # 上次保存（消息数据持久化）的时刻 ( time.time(), 秒 )

    _blacklist_answer = defaultdict(set)
    _blacklist_answer_reserve = defaultdict(set)

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

        if len(self.chat_data.raw_message.strip()) == 0:
            return False

        group_id = self.chat_data.group_id
        if group_id in Chat._message_dict:
            group_msgs = Chat._message_dict[group_id]
            if group_msgs:
                group_pre_msg = group_msgs[-1]
            else:
                group_pre_msg = None

            # 群里的上一条发言
            await self._context_insert(group_pre_msg)

            user_id = self.chat_data.user_id
            if group_pre_msg and group_pre_msg.user_id != user_id:
                # 该用户在群里的上一条发言（倒序三句之内）
                for msg in group_msgs[:-3:-1]:
                    if msg.user_id == user_id:
                        await self._context_insert(msg)
                        break

        await self._message_insert()
        return True

    async def answer(self) -> AsyncGenerator[Message, None, None] | None:
        """
        回复这句话，可能会分多次回复，也可能不回复
        """
        # 不回复太短的对话，大部分是“？”、“草”
        if self.chat_data.is_plain_text and len(self.chat_data.plain_text) < 2:
            return None

        # # 不要一直回复同一个内容
        # if self.chat_data.raw_message == latest_reply['pre_raw_message']:
        #     return None
        # 有人复读了牛牛的回复，不继续回复
        # if self.chat_data.raw_message == latest_reply['reply']:
        #    return None

        results = await self._context_find()
        if not results:
            return None

        group_id = self.chat_data.group_id
        bot_id = self.chat_data.bot_id
        group_bot_replies = Chat._reply_dict[group_id][bot_id]

        raw_message = self.chat_data.raw_message
        keywords = self.chat_data.keywords
        async with Chat._reply_lock:
            group_bot_replies.append({
                "time": int(time.time()),
                "pre_raw_message": raw_message,
                "pre_keywords": keywords,
                "reply": Chat.REPLY_FLAG,
                "reply_keywords": Chat.REPLY_FLAG,
            })

        async def yield_results(results: tuple[list[str], str]) -> AsyncGenerator[Message, None, None]:
            answer_list, answer_keywords = results
            group_bot_replies = Chat._reply_dict[group_id][bot_id]
            for item in answer_list:
                async with Chat._reply_lock:
                    group_bot_replies.append({
                        "time": int(time.time()),
                        "pre_raw_message": raw_message,
                        "pre_keywords": keywords,
                        "reply": item,
                        "reply_keywords": answer_keywords,
                    })
                if "[CQ:" not in item:
                    async with Chat._topics_lock:
                        Chat._recent_topics[group_id] += [
                            k for k in answer_keywords.split(" ") if not k.startswith("牛牛")
                        ]
                async with Chat._topics_lock:
                    Chat._recent_topics[group_id] += [
                        k for k in self.chat_data._keywords_list if not k.startswith("牛牛")
                    ]
                # if "[CQ:" not in item and len(item) > Chat.DRUNK_TTS_THRESHOLD and await self.config.drunkenness():
                #     yield Message(Chat._text_to_speech(item))
                yield Message(item)

            async with Chat._reply_lock:
                group_bot_replies = group_bot_replies[-Chat.SAVE_RESERVED_SIZE :]

        return yield_results(results)

    @staticmethod
    async def reply_post_proc(raw_message: str, new_msg: str, bot_id: int, group_id: int) -> bool:
        """
        对 bot 回复的消息进行后处理，将缓存替换为处理后的消息
        """

        if raw_message == new_msg:
            return True

        reply_data = Chat._reply_dict[group_id][bot_id][::-1]
        for item in reply_data:
            if item["reply"] == raw_message:
                async with Chat._reply_lock:
                    item["reply"] = new_msg
                return True
        return False

    @staticmethod
    async def speak() -> tuple[int, int, list[Message], int | None] | None:
        """
        主动发言，返回当前最希望发言的 bot 账号、群号、发言消息 List、戳一戳目标，也有可能不发言
        """

        basic_msgs_len = 10
        basic_delay = 600

        def group_popularity_cmp(lhs: tuple[int, list[MessageModel]], rhs: tuple[int, list[MessageModel]]) -> int:
            def cmp(a: int, b: int):
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
        popularity = sorted(Chat._message_dict.items(), key=cmp_to_key(group_popularity_cmp))

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

            ban_keywords = await Chat._find_ban_keywords(context=None, group_id=group_id)

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

            available_messages = list(filter(msg_filter, Chat._message_dict[group_id]))
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
                target_id = random.choice(Chat._message_dict[group_id]).user_id

            return (bot_id, group_id, speak_list, target_id)

        return None

    @staticmethod
    async def ban(group_id: int, bot_id: int, ban_raw_message: str, reason: str) -> bool:
        """
        禁止以后回复这句话，仅对该群有效果
        """

        if group_id not in Chat._reply_dict:
            return False

        ban_reply = None
        reply_data = Chat._reply_dict[group_id][bot_id][::-1]

        for reply in reply_data:
            cur_reply = reply["reply"]
            # 为空时就直接 ban 最后一条回复
            if not ban_raw_message or ban_raw_message in cur_reply:
                ban_reply = reply
                break

        # 这种情况一般是有些 CQ 码，牛牛发送的时候，和被回复的时候，里面的内容不一样
        if not ban_reply:
            search = re.search(r"(\[CQ:[a-zA-z0-9-_.]+)", ban_raw_message)
            if search:
                type_keyword = search.group(1)
                for reply in reply_data:
                    cur_reply = reply["reply"]
                    if type_keyword in cur_reply:
                        ban_reply = reply
                        break

        if not ban_reply:
            return False

        pre_keywords = reply["pre_keywords"]
        keywords = reply["reply_keywords"]

        context_to_ban = await Context.find_one(Context.keywords == pre_keywords)
        if context_to_ban:
            ban_reason = Ban(keywords=keywords, group_id=group_id, reason=reason, time=int(time.time()))
            context_to_ban.ban.append(ban_reason)
            await context_to_ban.save()

        if keywords in Chat._blacklist_answer_reserve[group_id]:
            Chat._blacklist_answer[group_id].add(keywords)
            if keywords in Chat._blacklist_answer_reserve[Chat.BLACKLIST_FLAG]:
                Chat._blacklist_answer[Chat.BLACKLIST_FLAG].add(keywords)
        else:
            Chat._blacklist_answer_reserve[group_id].add(keywords)

        return True

    @staticmethod
    async def get_random_message_from_each_group() -> dict[int, MessageModel]:
        """
        获取每个群近期一条随机发言

        TODO: 随机权重可以改为 keywords 出现频率 或 用户发言频率 正相关
        """

        return {
            group_id: random.choice(group_msgs) for group_id, group_msgs in Chat._message_dict.items() if group_msgs
        }

    async def _message_insert(self):
        group_id = self.chat_data.group_id

        async with Chat._message_lock:
            Chat._message_dict[group_id].append(
                MessageModel(
                    group_id=group_id,
                    user_id=self.chat_data.user_id,
                    bot_id=self.chat_data.bot_id,
                    raw_message=self.chat_data.raw_message,
                    is_plain_text=self.chat_data.is_plain_text,
                    plain_text=self.chat_data.plain_text,
                    keywords=self.chat_data.keywords,
                    time=self.chat_data.time,
                )
            )

        if self.chat_data.is_plain_text:
            async with Chat._topics_lock:
                Chat._recent_topics[group_id] += [k for k in self.chat_data._keywords_list if not k.startswith("牛牛")]

        cur_time = self.chat_data.time
        if Chat._late_save_time == 0:
            Chat._late_save_time = cur_time - 1
            return

        if len(Chat._message_dict[group_id]) > Chat.SAVE_COUNT_THRESHOLD:
            await Chat._sync(cur_time)

        elif cur_time - Chat._late_save_time > Chat.SAVE_TIME_THRESHOLD:
            await Chat._sync(cur_time)

    @staticmethod
    async def _sync(cur_time: int = int(time.time())):
        """
        持久化
        """

        async with Chat._message_lock:
            save_list = [
                msg
                for group_msgs in Chat._message_dict.values()
                for msg in group_msgs
                if msg.time > Chat._late_save_time
            ]
            if not save_list:
                return

            new_dict = {
                group_id: group_msgs[-Chat.SAVE_RESERVED_SIZE :] for group_id, group_msgs in Chat._message_dict.items()
            }
            Chat._message_dict.clear()
            Chat._message_dict.update(new_dict)

            Chat._late_save_time = cur_time

        await MessageModel.insert_many(save_list)

    async def _context_insert(self, pre_msg: MessageModel):
        if not pre_msg:
            return

        raw_message = self.chat_data.raw_message

        # 在复读，不学
        if pre_msg.raw_message == raw_message:
            return

        # 回复别人的，不学
        if "[CQ:reply," in raw_message:
            return

        keywords = self.chat_data.keywords
        group_id = self.chat_data.group_id
        pre_keywords = pre_msg.keywords
        cur_time = self.chat_data.time

        context = await Context.find_one(Context.keywords == pre_keywords)
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
                if self.chat_data.is_plain_text:
                    context.answers[answer_index].messages.append(raw_message)
            else:
                context.answers.append(
                    Answer(keywords=keywords, group_id=group_id, count=1, time=cur_time, messages=[raw_message])
                )
            context.time = cur_time
            context.trigger_count += 1
            await context.save()

        else:
            context = Context(
                keywords=pre_keywords,
                time=cur_time,
                trigger_count=1,
                answers=[Answer(keywords=keywords, group_id=group_id, count=1, time=cur_time, messages=[raw_message])],
            )
            await context.insert()

    async def _context_find(self) -> tuple[list[str], str] | None:
        group_id = self.chat_data.group_id
        raw_message = self.chat_data.raw_message
        keywords = self.chat_data.keywords
        bot_id = self.chat_data.bot_id

        # 复读！
        if group_id in Chat._message_dict:
            group_msgs = Chat._message_dict[group_id]
            if len(group_msgs) >= Chat.REPEAT_THRESHOLD and all(
                item.raw_message == raw_message for item in group_msgs[-Chat.REPEAT_THRESHOLD + 1 :]
            ):
                # 到这里说明当前群里是在复读
                group_bot_replies = Chat._reply_dict[group_id][bot_id]
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

        context = await Context.find_one(Context.keywords == keywords)

        if not context:
            return None

        is_drunk = await self.config.drunkenness() > 0

        if is_drunk:
            answer_count_threshold = 1
        else:
            answer_count_threshold = random.choices(
                Chat.ANSWER_THRESHOLD_CHOICE_LIST, weights=Chat.ANSWER_THRESHOLD_WEIGHTS
            )[0]
            if self.chat_data.keywords_len == ChatData._keywords_size:
                answer_count_threshold -= 1

        if self.chat_data.to_me:
            cross_group_threshold = 1
        else:
            cross_group_threshold = Chat.CROSS_GROUP_THRESHOLD

        ban_keywords = await Chat._find_ban_keywords(context=context, group_id=group_id)

        candidate_answers: dict[str, Answer] = {}
        other_group_cache = {}
        answers_count = defaultdict(int)
        recent_replies = [r["reply_keywords"] for r in Chat._reply_dict[group_id][bot_id][-Chat.DUPLICATE_REPLY :]]
        recent_message = [m.raw_message for m in Chat._message_dict[group_id][-Chat.DUPLICATE_REPLY :]]

        def candidate_append(dst: dict[str, Answer], answer: Answer):
            answer_key = answer.keywords
            if "[CQ:" not in answer_key:
                topics = Chat._recent_topics[group_id]
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
            if self.chat_data.is_image and "[CQ:" not in sample_msg:
                # 图片消息不回复纯文本。图片经常是表情包，后面的纯文本啥都有，很乱
                continue
            if sample_msg.startswith("牛牛"):
                if not self.chat_data.to_me or len(sample_msg) <= 6:
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
            min(answer.count, 10) + answer._topical * Chat.TOPICS_IMPORTANCE for answer in candidate_answers.values()
        ]
        final_answer = random.choices(list(candidate_answers.values()), weights=weights)[0]
        answer_str = random.choice(final_answer.messages)
        answer_keywords = final_answer.keywords
        answer_str = answer_str.removeprefix("牛牛")

        if 0 < answer_str.count("，") <= 3 and "[CQ:" not in answer_str and random.random() < Chat.SPLIT_PROBABILITY:
            return (answer_str.split("，"), answer_keywords)
        return (
            [
                answer_str,
            ],
            answer_keywords,
        )

    @staticmethod
    async def update_global_blacklist() -> None:
        await Chat._select_blacklist()

        keywords_dict = defaultdict(int)
        global_blacklist = set()
        for keywords_list in Chat._blacklist_answer.values():
            for keywords in keywords_list:
                keywords_dict[keywords] += 1
                if keywords_dict[keywords] == Chat.CROSS_GROUP_THRESHOLD:
                    global_blacklist.add(keywords)

        Chat._blacklist_answer[Chat.BLACKLIST_FLAG] |= global_blacklist

    @staticmethod
    async def _select_blacklist() -> None:
        all_blacklist = await BlackList.find_all().to_list()

        for item in all_blacklist:
            group_id = item.group_id
            if item.answers:
                Chat._blacklist_answer[group_id] |= set(item.answers)
            if item.answers_reserve:
                Chat._blacklist_answer_reserve[group_id] |= set(item.answers_reserve)

    @staticmethod
    async def _sync_blacklist() -> None:
        await Chat._select_blacklist()

        for group_id, answers in Chat._blacklist_answer.items():
            if not len(answers):
                continue
            await BlackList.find_one(BlackList.group_id == group_id).upsert(
                {"$set": {"answers": list(answers)}}, on_insert=BlackList(group_id=group_id, answers=list(answers))
            )

        for group_id, answers_set in Chat._blacklist_answer_reserve.items():
            if not len(answers_set):
                continue
            filtered_answers = answers_set
            if group_id in Chat._blacklist_answer:
                filtered_answers = answers_set - Chat._blacklist_answer[group_id]

            await BlackList.find_one(BlackList.group_id == group_id).upsert(
                {"$set": {"answers_reserve": list(filtered_answers)}},
                on_insert=BlackList(group_id=group_id, answers_reserve=list(filtered_answers)),
            )

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
    async def _find_ban_keywords(context: Context | None, group_id) -> set:
        """
        找到在 group_id 群中对应 context 不能回复的关键词
        """

        # 全局的黑名单
        ban_keywords = Chat._blacklist_answer[Chat.BLACKLIST_FLAG] | Chat._blacklist_answer[group_id]
        # 针对单条回复的黑名单
        if context is not None and context.ban:
            ban_count = defaultdict(int)
            for ban in context.ban:
                ban_key = ban.keywords
                if ban.group_id in {group_id, Chat.BLACKLIST_FLAG}:
                    ban_keywords.add(ban_key)
                else:
                    # 超过 N 个群都把这句话 ban 了，那就全局 ban 掉
                    ban_count[ban_key] += 1
                    if ban_count[ban_key] == Chat.CROSS_GROUP_THRESHOLD:
                        ban_keywords.add(ban_key)
        return ban_keywords

    @staticmethod
    async def sync():
        await Chat._sync()
        await Chat._sync_blacklist()


if __name__ == "__main__":
    # Chat.clearup_context()
    # # while True:
    test_data: ChatData = ChatData(
        group_id=1234567,
        user_id=1111111,
        raw_message="完了又有新bug",
        plain_text="完了又有新bug",
        time=time.time(),
        bot_id=0,
    )

    test_chat: Chat = Chat(test_data)

    print(test_chat.answer())
    test_chat.learn()

    test_answer_data: ChatData = ChatData(
        group_id=1234567,
        user_id=1111111,
        raw_message="完了又有新bug",
        plain_text="完了又有新bug",
        time=time.time(),
        bot_id=0,
    )

    test_answer: Chat = Chat(test_answer_data)
    print(test_chat.answer())
    test_answer.learn()

    # time.sleep(5)
    # print(Chat.speak())
