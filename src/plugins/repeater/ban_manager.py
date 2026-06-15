import re
import time
from collections import defaultdict

from nonebot import logger

from src.foundation.db import Ban, Context, make_blacklist_repository
from src.foundation.db.context_repo_access import context_repo

from .config import get_repeater_config

plugin_config = get_repeater_config()


blacklist_repo = make_blacklist_repository()


class BanManager:
    """复读插件的禁言/黑名单管理"""

    # Constants
    BLACKLIST_FLAG = 114514
    CROSS_GROUP_THRESHOLD = plugin_config.cross_group_threshold

    # Class variables
    _blacklist_answer = defaultdict(set)  # 每个群的封禁关键词
    _blacklist_answer_reserve = defaultdict(set)  # 候选黑名单

    @staticmethod
    def find_ban_reply(group_id: int, bot_id: int, ban_raw_message: str, reply_dict: dict) -> dict | None:
        if group_id not in reply_dict:
            return None

        reply_data = reply_dict[group_id][bot_id][::-1]
        ban_reply = None

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

        return ban_reply

    @staticmethod
    def iter_ban_bot_ids(group_id: int, bot_id: int, reply_dict: dict) -> list[int]:
        bot_ids = [bot_id]
        if group_id not in reply_dict:
            return bot_ids
        for bid in reply_dict[group_id]:
            if bid not in bot_ids:
                bot_ids.append(bid)
        return bot_ids

    @staticmethod
    async def find_ban_reply_fallback(group_id: int, ban_raw_message: str) -> dict | None:
        if not ban_raw_message.strip():
            return None
        find_target = getattr(context_repo, "find_ban_reply_target", None)
        if not callable(find_target):
            return None
        try:
            found = await find_target(group_id, ban_raw_message)
        except RuntimeError as exc:
            logger.debug("repeater ban fallback skipped for group {}: {}", group_id, exc)
            return None
        if not found:
            return None
        pre_keywords, reply_keywords = found
        return {
            "pre_keywords": pre_keywords,
            "reply_keywords": reply_keywords,
        }

    @staticmethod
    async def ban(group_id: int, bot_id: int, ban_raw_message: str, reason: str, reply_dict: dict) -> bool:
        """
        禁止以后回复这句话，仅对该群有效果
        """
        ban_reply = None
        for candidate_bot_id in BanManager.iter_ban_bot_ids(group_id, bot_id, reply_dict):
            ban_reply = BanManager.find_ban_reply(group_id, candidate_bot_id, ban_raw_message, reply_dict)
            if ban_reply:
                break
        if not ban_reply:
            ban_reply = await BanManager.find_ban_reply_fallback(group_id, ban_raw_message)
        if not ban_reply:
            return False

        pre_keywords = ban_reply["pre_keywords"]
        keywords = ban_reply["reply_keywords"]

        # 通过 append_ban 原子追加
        # Context 不存在时为 no-op
        ban_reason = Ban(keywords=keywords, group_id=group_id, reason=reason, time=int(time.time()))
        await context_repo.append_ban(pre_keywords, ban_reason)

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
        all_blacklist = await blacklist_repo.find_all()

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
            await blacklist_repo.upsert_answers(group_id, list(answers))

        for group_id, answers_set in BanManager._blacklist_answer_reserve.items():
            if not len(answers_set):
                continue
            filtered_answers = answers_set
            if group_id in BanManager._blacklist_answer:
                filtered_answers = answers_set - BanManager._blacklist_answer[group_id]

            await blacklist_repo.upsert_answers_reserve(group_id, list(filtered_answers))
