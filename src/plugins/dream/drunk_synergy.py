from __future__ import annotations

import random
import time
from typing import TYPE_CHECKING

from nonebot import logger
from nonebot.adapters.onebot.v11 import Bot, Message, MessageSegment
from nonebot.exception import ActionFailed

from src.common.db import get_db_backend
from src.common.utils import is_bot_admin

from .history_bottle import DREAM_KEY_PREFIX

if TYPE_CHECKING:
    from src.common.config import BotConfig

_TAKE_NAME_CARDS = ("帕拉斯", "牛牛", "牛牛喝酒", "牛牛干杯", "牛牛继续喝")
_USER_HISTORY_MAX_AGE_SEC = 90 * 86400
_RANDOM_USER_SAMPLE = 10
_RANDOM_LINE_SAMPLE = 20


def drift_style_at(nickname: str) -> str:
    n = (nickname or "").strip() or "某位博士"
    return n if n.startswith("@") else f"@{n}"


async def pick_random_member_user_id(*, bot_id: int, group_id: int) -> int | None:
    backend = get_db_backend()
    if backend == "mongodb":
        return await _mongo_pick_random_user(bot_id, group_id)
    if backend == "postgresql":
        return await _pg_pick_random_user(bot_id, group_id)
    return None


async def _mongo_pick_random_user(bot_id: int, group_id: int) -> int | None:
    from src.common.db.modules import Message

    coll = Message.get_pymongo_collection()
    now = int(time.time())
    cutoff = now - _USER_HISTORY_MAX_AGE_SEC
    match: dict = {
        "group_id": group_id,
        "bot_id": bot_id,
        "user_id": {"$ne": bot_id},
        "time": {"$gte": cutoff},
    }
    pipeline = [{"$match": match}, {"$sample": {"size": _RANDOM_USER_SAMPLE}}]
    try:
        docs = [d async for d in coll.aggregate(pipeline)]
    except Exception as e:
        logger.debug("drunk_synergy mongo pick user failed: {}", e)
        return None
    if not docs:
        return None
    d = random.choice(docs)
    uid = d.get("user_id")
    return int(uid) if uid is not None else None


async def _pg_pick_random_user(bot_id: int, group_id: int) -> int | None:
    from sqlalchemy import func, select

    from src.common.db.repository_pg import MessageRow, get_session

    now = int(time.time())
    cutoff = now - _USER_HISTORY_MAX_AGE_SEC
    try:
        async with get_session() as session:
            stmt = (
                select(MessageRow.user_id)
                .where(MessageRow.group_id == group_id)
                .where(MessageRow.bot_id == bot_id)
                .where(MessageRow.user_id != bot_id)
                .where(MessageRow.time >= cutoff)
                .order_by(func.random())
                .limit(_RANDOM_USER_SAMPLE)
            )
            r = await session.execute(stmt)
            rows = [row[0] for row in r.all()]
    except Exception as e:
        logger.debug("drunk_synergy pg pick user failed: {}", e)
        return None
    if not rows:
        return None
    return int(random.choice(rows))


async def sample_user_non_dream_plain_line(*, bot_id: int, group_id: int, user_id: int) -> str | None:
    backend = get_db_backend()
    if backend == "mongodb":
        return await _mongo_pick_plain_line(bot_id, group_id, user_id)
    if backend == "postgresql":
        return await _pg_pick_plain_line(bot_id, group_id, user_id)
    return None


async def _mongo_pick_plain_line(bot_id: int, group_id: int, user_id: int) -> str | None:
    from src.common.db.modules import Message

    coll = Message.get_pymongo_collection()
    now = int(time.time())
    cutoff = now - _USER_HISTORY_MAX_AGE_SEC
    match: dict = {
        "group_id": group_id,
        "bot_id": bot_id,
        "user_id": user_id,
        "time": {"$gte": cutoff},
    }
    pipeline = [{"$match": match}, {"$sample": {"size": _RANDOM_LINE_SAMPLE}}]
    try:
        docs = [d async for d in coll.aggregate(pipeline)]
    except Exception as e:
        logger.debug("drunk_synergy mongo pick line failed: {}", e)
        return None
    random.shuffle(docs)
    for doc in docs:
        kw = doc.get("keywords") or ""
        if isinstance(kw, str) and kw.startswith(DREAM_KEY_PREFIX):
            continue
        plain = (doc.get("plain_text") or "").strip()
        if len(plain) < 2 or plain.startswith("[CQ:"):
            continue
        return plain[:800]
    return None


async def _pg_pick_plain_line(bot_id: int, group_id: int, user_id: int) -> str | None:
    from sqlalchemy import func, select

    from src.common.db.repository_pg import MessageRow, get_session

    now = int(time.time())
    cutoff = now - _USER_HISTORY_MAX_AGE_SEC
    try:
        async with get_session() as session:
            stmt = (
                select(MessageRow.plain_text, MessageRow.keywords)
                .where(MessageRow.group_id == group_id)
                .where(MessageRow.bot_id == bot_id)
                .where(MessageRow.user_id == user_id)
                .where(MessageRow.time >= cutoff)
                .order_by(func.random())
                .limit(_RANDOM_LINE_SAMPLE)
            )
            r = await session.execute(stmt)
            rows = list(r.all())
    except Exception as e:
        logger.debug("drunk_synergy pg pick line failed: {}", e)
        return None
    random.shuffle(rows)
    for plain, keywords in rows:
        kw = keywords or ""
        if kw.startswith(DREAM_KEY_PREFIX):
            continue
        p = (plain or "").strip()
        if len(p) < 2 or p.startswith("[CQ:"):
            continue
        return p[:800]
    return None


async def try_drunk_dream_take_name(*, bot: Bot, bot_id: int, group_id: int, cfg: BotConfig) -> tuple[int, str] | None:
    if not await is_bot_admin(bot_id, group_id, True):
        return None
    uid = await pick_random_member_user_id(bot_id=bot_id, group_id=group_id)
    if uid is None:
        return None
    try:
        info = await bot.call_api(
            "get_group_member_info",
            **{"group_id": group_id, "user_id": uid, "no_cache": True},
        )
    except ActionFailed:
        return None
    victim_label = (info.get("card") or info.get("nickname") or str(uid)).strip() or str(uid)
    try:
        await bot.call_api(
            "set_group_card",
            **{"group_id": group_id, "user_id": bot_id, "card": victim_label[:60]},
        )
        await bot.call_api(
            "set_group_card",
            **{"group_id": group_id, "user_id": uid, "card": random.choice(_TAKE_NAME_CARDS)},
        )
        await cfg.update_taken_name(uid)
    except ActionFailed as e:
        logger.debug("try_drunk_dream_take_name ActionFailed: {}", e)
        return None
    return (uid, victim_label)


async def send_one_random_history_line(
    bot: Bot,
    *,
    bot_id: int,
    group_id: int,
    user_id: int,
    display_name: str | None = None,
) -> None:
    line = await sample_user_non_dream_plain_line(bot_id=bot_id, group_id=group_id, user_id=user_id)
    if not line:
        return
    nick = (display_name or "").strip() or str(user_id)
    body = f"{drift_style_at(nick)}：{line}"
    await bot.send_group_msg(group_id=group_id, message=Message(MessageSegment.text(body)))
