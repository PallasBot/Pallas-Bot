import random
import time
from collections import defaultdict
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import TYPE_CHECKING

from nonebot import get_bots, logger
from nonebot.adapters.onebot.v11 import Message

from src.foundation.config import BotConfig
from src.foundation.db import Answer
from src.foundation.db.context_repo_access import context_repo
from src.foundation.db.pool_budget import is_pg_pool_timeout_error, pg_pool_under_pressure
from src.platform.shard import context as shard_ctx

from .ban_manager import BanManager
from .config import get_repeater_config
from .topic_utils import filtered_recent_topics

if TYPE_CHECKING:
    from .model import ChatData


plugin_config = get_repeater_config()


@dataclass(frozen=True)
class ReplyBundle:
    """一次 context 检索结果；fanout 时各牛从 message_pool 轻量随机，不再重复查库。"""

    answer_list: list[str]
    answer_keywords: str
    message_pool: list[str]


class Responder:
    """回复决策模块，负责根据上下文检索候选回答并选择最终回复"""

    NON_PLAIN_CORPUS_SKIP_LEN = 256
    SHORT_PLAIN_SKIP_LEN = 2
    EMPTY_KEYWORDS_PLAIN_SKIP_LEN = 4
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
    def _repeat_ignore_user_ids() -> set[int]:
        from src.platform.multi_bot.fleet import get_catalog_bot_ids

        if shard_ctx.sharding_active():
            ids = set(get_catalog_bot_ids())
        else:
            ids = {int(b.self_id) for b in get_bots().values()}
        ids.update(plugin_config.repeat_ignore_user_ids)
        return ids

    @staticmethod
    def _human_messages_for_repeat(group_msgs: list) -> list:
        ignore = Responder._repeat_ignore_user_ids()
        return [m for m in group_msgs if (uid := getattr(m, "user_id", None)) is None or uid not in ignore]

    @staticmethod
    def should_skip_context_lookup(chat_data: "ChatData", keywords: str) -> bool:
        if getattr(chat_data, "is_plain_text", False):
            if getattr(chat_data, "to_me", False):
                return False
            plain = str(getattr(chat_data, "plain_text", "") or "").strip()
            if shard_ctx.sharding_active():
                return not plain
            keywords_len = int(getattr(chat_data, "keywords_len", 0) or 0)
            if keywords_len == 0:
                return 0 < len(plain) <= Responder.EMPTY_KEYWORDS_PLAIN_SKIP_LEN
            if keywords_len == 1:
                return 0 < len(plain) <= Responder.SHORT_PLAIN_SKIP_LEN
            return False
        plain = str(getattr(chat_data, "plain_text", "") or "").strip()
        # 纯 CQ / 媒体消息没有可复用的语义，直接跳过语料 miss。
        if not plain:
            return True
        if getattr(chat_data, "keywords_len", 0) != 0:
            return False
        return len(keywords) >= Responder.NON_PLAIN_CORPUS_SKIP_LEN

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
            if not shard_ctx.sharding_active():
                return None

        from .message_store import MessageStore

        bundle = await Responder.find_reply_bundle(
            chat_data, config, reply_dict, MessageStore._message_dict, recent_topics
        )
        if not bundle:
            return None

        return await Responder.answer_from_bundle(
            bundle,
            chat_data,
            config,
            reply_dict,
            reply_lock,
            recent_topics,
            topics_lock,
        )

    @staticmethod
    async def answer_from_bundle(
        bundle: ReplyBundle,
        chat_data: "ChatData",
        config: BotConfig,
        reply_dict,
        reply_lock,
        recent_topics,
        topics_lock,
        *,
        plan: tuple[list[str], str] | None = None,
    ) -> AsyncGenerator[Message, None] | None:
        answer_list, answer_keywords = plan if plan is not None else (bundle.answer_list, bundle.answer_keywords)
        if not answer_list:
            return None

        group_id = chat_data.group_id
        bot_id = chat_data.bot_id
        group_bot_replies = reply_dict[group_id][bot_id]

        raw_message = chat_data.raw_message
        keywords = chat_data.keywords
        from .reply_record_sync import publish_reply_record

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
                        publish_reply_record(group_id, bot_id, group_bot_replies[-1])
                    if "[CQ:" not in item:
                        async with topics_lock:
                            recent_topics[group_id] += filtered_recent_topics(answer_keywords.split(" "))
                    async with topics_lock:
                        recent_topics[group_id] += filtered_recent_topics(chat_data._keywords_list)
                    yield Message(item)
            finally:
                async with reply_lock:
                    reply_dict[group_id][bot_id][:] = reply_dict[group_id][bot_id][-Responder.SAVE_RESERVED_SIZE :]

        return yield_results((answer_list, answer_keywords))

    @staticmethod
    async def find_reply_bundle(
        chat_data: "ChatData",
        config: BotConfig,
        reply_dict,
        message_dict,
        recent_topics,
    ) -> ReplyBundle | None:
        found = await Responder._context_find_with_pool(chat_data, config, reply_dict, message_dict, recent_topics)
        if not found:
            return None
        plan, message_pool = found
        answer_list, answer_keywords = plan
        return ReplyBundle(
            answer_list=answer_list,
            answer_keywords=answer_keywords,
            message_pool=message_pool or list(answer_list),
        )

    @staticmethod
    async def _context_find(
        chat_data: "ChatData",
        config: BotConfig,
        reply_dict,
        message_dict,
        recent_topics,
    ) -> tuple[list[str], str] | None:
        found = await Responder._context_find_with_pool(chat_data, config, reply_dict, message_dict, recent_topics)
        if not found:
            return None
        plan, _ = found
        return plan

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
                    from .reply_record_sync import publish_reply_record

                    publish_reply_record(group_id, bot_id, item)
                    return True
        return False

    @staticmethod
    async def _context_find_with_pool(
        chat_data: "ChatData",
        config: BotConfig,
        reply_dict,
        message_dict,
        recent_topics,
    ) -> tuple[tuple[list[str], str], list[str]] | None:
        group_id = chat_data.group_id
        raw_message = chat_data.raw_message
        bot_id = chat_data.bot_id

        # 复读！
        rt = Responder.REPEAT_THRESHOLD
        if rt >= 2 and group_id in message_dict:
            group_msgs = message_dict[group_id]
            human_msgs = Responder._human_messages_for_repeat(group_msgs)
            tail = rt - 1
            if len(human_msgs) >= tail and all(item.raw_message == raw_message for item in human_msgs[-tail:]):
                # 到这里说明当前群里是在复读
                group_bot_replies = reply_dict[group_id][bot_id]
                if len(group_bot_replies) and group_bot_replies[-1]["reply"] != raw_message:
                    keywords = chat_data.keywords
                    repeat_plan = ([raw_message], keywords)
                    return repeat_plan, list(repeat_plan[0])
                else:
                    # 复读过一次就不再回复这句话了
                    return None

        plain_text = str(getattr(chat_data, "plain_text", "") or "").strip()
        if not getattr(chat_data, "is_plain_text", False) and not plain_text:
            return None

        keywords = chat_data.keywords
        if not keywords:
            return None
        if Responder.should_skip_context_lookup(chat_data, keywords):
            logger.debug(
                "repeater.skip_context_lookup group_id={} bot_id={} raw_len={} kw_len={}",
                group_id,
                bot_id,
                len(raw_message),
                len(keywords),
            )
            return None

        if pg_pool_under_pressure(threshold=0.55):
            logger.debug(
                "repeater.skip_reply_context pg_pool_pressure group_id={} bot_id={} kw_len={}",
                group_id,
                bot_id,
                len(keywords),
            )
            return None

        find_reply = getattr(context_repo, "find_by_keywords_for_reply", None)
        try:
            if callable(find_reply):
                context = await find_reply(keywords)
            else:
                context = await context_repo.find_by_keywords(keywords)
        except Exception as exc:
            if is_pg_pool_timeout_error(exc):
                logger.debug(
                    "repeater.skip_reply_context db_timeout group_id={} bot_id={} kw_len={}",
                    group_id,
                    bot_id,
                    len(keywords),
                )
                return None
            raise

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

            if not answer.messages:
                continue

            sample_msg = answer.messages[0]
            if chat_data.is_image and "[CQ:" not in sample_msg:
                # 图片消息不回复纯文本。图片经常是表情包，后面的纯文本啥都有，很乱
                continue
            if sample_msg.startswith("牛牛"):
                if not chat_data.to_me or len(sample_msg) <= 6:
                    # 这种一般是学反过来的，比如有人教“牛牛你好”——“你好”
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

        message_pool: list[str] = []
        for answer in candidate_answers.values():
            for sample in answer.messages:
                text = sample.removeprefix("牛牛")
                if text and text not in message_pool:
                    message_pool.append(text)

        weights = [
            min(answer.count, 10) + answer._topical * Responder.TOPICS_IMPORTANCE
            for answer in candidate_answers.values()
        ]
        final_answer = random.choices(list(candidate_answers.values()), weights=weights)[0]
        answer_str = random.choice(final_answer.messages)
        answer_keywords = final_answer.keywords
        answer_str = answer_str.removeprefix("牛牛")

        plan = Responder._plan_from_answer_text(answer_str, answer_keywords)
        if plan is None:
            return None
        if not message_pool:
            message_pool = list(plan[0])
        return plan, message_pool

    @staticmethod
    def _plan_from_answer_text(answer_str: str, answer_keywords: str) -> tuple[list[str], str] | None:
        if not answer_str:
            return None
        if (
            0 < answer_str.count("，") <= 3
            and "[CQ:" not in answer_str
            and random.random() < Responder.SPLIT_PROBABILITY
        ):
            return (answer_str.split("，"), answer_keywords)
        return ([answer_str], answer_keywords)

    @staticmethod
    def pick_fanout_plan(bundle: ReplyBundle) -> tuple[list[str], str]:
        """各牛从共享候选池随机一句，不再重复 context 检索。"""
        pool = bundle.message_pool
        if len(pool) <= 1:
            return bundle.answer_list, bundle.answer_keywords
        text = random.choice(pool)
        plan = Responder._plan_from_answer_text(text, bundle.answer_keywords)
        if plan is None:
            return bundle.answer_list, bundle.answer_keywords
        return plan
