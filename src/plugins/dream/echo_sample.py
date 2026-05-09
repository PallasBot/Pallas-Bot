from __future__ import annotations

import re

from src.common.db import get_db_backend

from .dream_labels import pick_pseudo_sender_at

_CQ_RE = re.compile(r"^\[CQ:")


async def sample_learned_echo_line() -> str | None:
    backend = get_db_backend()
    if backend == "mongodb":
        return await _mongo_sample() or None
    if backend == "postgresql":
        return await _pg_sample() or None
    return None


async def _mongo_sample() -> str | None:
    from src.common.db.modules import Context, Message

    coll = Context.get_pymongo_collection()
    pipeline = [
        {"$unwind": "$answers"},
        {"$unwind": "$answers.messages"},
        {
            "$match": {
                "answers.messages": {"$regex": r"^(?!\[CQ:).{2,200}$"},
            }
        },
        {"$sample": {"size": 1}},
        {"$project": {"_id": 0, "t": "$answers.messages"}},
    ]
    try:
        cursor = coll.aggregate(pipeline)
        async for doc in cursor:
            t = doc.get("t")
            if isinstance(t, str):
                s = t.strip()
                if s and not _CQ_RE.match(s) and "\n" not in s:
                    return s
    except Exception:
        pass

    try:
        mc = Message.get_pymongo_collection()
        pipe2 = [
            {"$match": {"is_plain_text": True, "plain_text": {"$regex": r"^.{2,200}$"}}},
            {"$sample": {"size": 1}},
            {"$project": {"_id": 0, "t": "$plain_text"}},
        ]
        cursor2 = mc.aggregate(pipe2)
        async for doc in cursor2:
            t = doc.get("t")
            if isinstance(t, str):
                s = t.strip()
                if s and not s.startswith("牛牛") and "\n" not in s:
                    return s
    except Exception:
        pass
    return None


async def _pg_sample() -> str | None:
    from sqlalchemy import func, not_, select

    from src.common.db.repository_pg import ContextAnswerMessageRow, MessageRow, get_session

    try:
        async with get_session() as session:
            r = await session.execute(
                select(ContextAnswerMessageRow.message)
                .where(not_(ContextAnswerMessageRow.message.startswith("[CQ:")))
                .where(func.length(ContextAnswerMessageRow.message).between(2, 200))
                .order_by(func.random())
                .limit(1)
            )
            row = r.scalar_one_or_none()
            if row and isinstance(row, str):
                s = row.strip()
                if s and "\n" not in s:
                    return s
    except Exception:
        pass

    try:
        async with get_session() as session:
            r2 = await session.execute(
                select(MessageRow.plain_text)
                .where(MessageRow.is_plain_text.is_(True))
                .where(func.length(MessageRow.plain_text).between(2, 200))
                .order_by(func.random())
                .limit(1)
            )
            row2 = r2.scalar_one_or_none()
            if row2 and isinstance(row2, str):
                s = row2.strip()
                if s and not s.startswith("牛牛") and "\n" not in s:
                    return s
    except Exception:
        pass
    return None


def random_echo_nickname() -> str:
    return pick_pseudo_sender_at()
