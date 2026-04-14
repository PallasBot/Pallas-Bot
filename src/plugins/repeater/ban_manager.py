import re
import time
from collections import defaultdict

from nonebot import get_plugin_config

from src.common.db import Ban, Context
from src.common.db.repository_impl import MongoBlackListRepository, MongoContextRepository

from .config import Config

plugin_config = get_plugin_config(Config)


_context_repo = MongoContextRepository()
_blacklist_repo = MongoBlackListRepository()


class BanManager:
    """Manages ban/blacklist functionality for the repeater plugin."""

    # Constants
    BLACKLIST_FLAG = 114514
    CROSS_GROUP_THRESHOLD = plugin_config.cross_group_threshold

    # Class variables
    _blacklist_answer = defaultdict(set)  # per-group banned keywords
    _blacklist_answer_reserve = defaultdict(set)  # reserve blacklist (second offense triggers real ban)

    @staticmethod
    async def ban(group_id: int, bot_id: int, ban_raw_message: str, reason: str, reply_dict: dict) -> bool:
        """
        禁止以后回复这句话，仅对该群有效果
        """

        if group_id not in reply_dict:
            return False

        ban_reply = None
        reply_data = reply_dict[group_id][bot_id][::-1]

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

        pre_keywords = ban_reply["pre_keywords"]
        keywords = ban_reply["reply_keywords"]

        context_to_ban = await _context_repo.find_by_keywords(pre_keywords)
        if context_to_ban:
            ban_reason = Ban(keywords=keywords, group_id=group_id, reason=reason, time=int(time.time()))
            context_to_ban.ban.append(ban_reason)
            await _context_repo.save(context_to_ban)

        if keywords in BanManager._blacklist_answer_reserve[group_id]:
            BanManager._blacklist_answer[group_id].add(keywords)
            if keywords in BanManager._blacklist_answer_reserve[BanManager.BLACKLIST_FLAG]:
                BanManager._blacklist_answer[BanManager.BLACKLIST_FLAG].add(keywords)
        else:
            BanManager._blacklist_answer_reserve[group_id].add(keywords)

        return True

    @staticmethod
    async def find_ban_keywords(context: Context | None, group_id) -> set:
        """
        找到在 group_id 群中对应 context 不能回复的关键词
        """

        # 全局的黑名单
        ban_keywords = BanManager._blacklist_answer[BanManager.BLACKLIST_FLAG] | BanManager._blacklist_answer[group_id]
        # 针对单条回复的黑名单
        if context is not None and context.ban:
            ban_count = defaultdict(int)
            for ban in context.ban:
                ban_key = ban.keywords
                if ban.group_id in {group_id, BanManager.BLACKLIST_FLAG}:
                    ban_keywords.add(ban_key)
                else:
                    # 超过 N 个群都把这句话 ban 了，那就全局 ban 掉
                    ban_count[ban_key] += 1
                    if ban_count[ban_key] == BanManager.CROSS_GROUP_THRESHOLD:
                        ban_keywords.add(ban_key)
        return ban_keywords

    @staticmethod
    async def update_global_blacklist() -> None:
        await BanManager._select_blacklist()

        keywords_dict = defaultdict(int)
        global_blacklist = set()
        for keywords_list in BanManager._blacklist_answer.values():
            for keywords in keywords_list:
                keywords_dict[keywords] += 1
                if keywords_dict[keywords] == BanManager.CROSS_GROUP_THRESHOLD:
                    global_blacklist.add(keywords)

        BanManager._blacklist_answer[BanManager.BLACKLIST_FLAG] |= global_blacklist

    @staticmethod
    async def _select_blacklist() -> None:
        all_blacklist = await _blacklist_repo.find_all()

        for item in all_blacklist:
            group_id = item.group_id
            if item.answers:
                BanManager._blacklist_answer[group_id] |= set(item.answers)
            if item.answers_reserve:
                BanManager._blacklist_answer_reserve[group_id] |= set(item.answers_reserve)

    @staticmethod
    async def _sync_blacklist() -> None:
        await BanManager._select_blacklist()

        for group_id, answers in BanManager._blacklist_answer.items():
            if not len(answers):
                continue
            await _blacklist_repo.upsert_answers(group_id, list(answers))

        for group_id, answers_set in BanManager._blacklist_answer_reserve.items():
            if not len(answers_set):
                continue
            filtered_answers = answers_set
            if group_id in BanManager._blacklist_answer:
                filtered_answers = answers_set - BanManager._blacklist_answer[group_id]

            await _blacklist_repo.upsert_answers_reserve(group_id, list(filtered_answers))
