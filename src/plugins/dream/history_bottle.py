from __future__ import annotations

import random
import re
import time
import urllib.parse

from nonebot import logger

from src.common.db import get_db_backend

from .http_utils import download_image_url
from .payload import DriftPayload

# 写入 message.keywords 的前缀（与复读侧 keywords 区分）
DREAM_KEY_PREFIX = "is_dream"
DREAM_RECORD_SEP = "\x1e"
_HISTORY_MAX_AGE_SEC = 90 * 86400


def _nickname_after_mark(keywords: str, mark: str) -> str:
    rest = keywords[len(mark) :]
    if rest.startswith(DREAM_RECORD_SEP):
        n = rest[len(DREAM_RECORD_SEP) :].strip()
        if n:
            return n[:120]
    return "某位博士"


def dream_display_name_from_keywords(keywords: str) -> str:
    if not isinstance(keywords, str):
        return "某位博士"
    if keywords.startswith(DREAM_KEY_PREFIX):
        return _nickname_after_mark(keywords, DREAM_KEY_PREFIX)
    return "某位博士"


def dream_keywords_for_insert(display_name: str) -> str:
    safe = (display_name or "").replace(DREAM_RECORD_SEP, " ").replace("\n", " ").strip() or "某位博士"
    return f"{DREAM_KEY_PREFIX}{DREAM_RECORD_SEP}{safe[:120]}"


def first_http_image_url_from_cq_raw(raw: str) -> str | None:
    if not raw or "[CQ:image," not in raw:
        return None
    for m in re.finditer(r"\[CQ:image,([^\]]+)\]", raw):
        inner = m.group(1)
        for part in inner.split(","):
            if part.startswith("url="):
                u = urllib.parse.unquote(part[4:], errors="replace").strip()
                if u.startswith(("http://", "https://")):
                    return u
            if part.startswith("file="):
                u = urllib.parse.unquote(part[5:], errors="replace").strip()
                if u.startswith(("http://", "https://")):
                    return u
    return None


async def sample_historical_drift(*, bot_id: int, exclude_group_id: int | None = None) -> DriftPayload | None:
    backend = get_db_backend()
    if backend == "mongodb":
        return await _mongo_pick(bot_id, exclude_group_id)
    if backend == "postgresql":
        return await _pg_pick(bot_id, exclude_group_id)
    return None


async def _mongo_pick(bot_id: int, exclude_gid: int | None) -> DriftPayload | None:
    from src.common.db.modules import Message

    coll = Message.get_pymongo_collection()
    now = int(time.time())
    cutoff = now - _HISTORY_MAX_AGE_SEC
    key_pat = f"^{re.escape(DREAM_KEY_PREFIX)}"
    match: dict = {
        "keywords": {"$regex": key_pat},
        "bot_id": bot_id,
        "time": {"$gte": cutoff},
    }
    if exclude_gid is not None:
        match["group_id"] = {"$ne": exclude_gid}
    pipeline = [
        {"$match": match},
        {"$sample": {"size": 12}},
    ]
    try:
        docs = [d async for d in coll.aggregate(pipeline)]
    except Exception as e:
        logger.debug("history_bottle mongo aggregate failed: {}", e)
        return None
    random.shuffle(docs)
    for doc in docs:
        kw = doc.get("keywords") or ""
        nick = dream_display_name_from_keywords(kw if isinstance(kw, str) else "")
        plain = (doc.get("plain_text") or "").strip()
        raw = doc.get("raw_message") or ""
        if len(plain) >= 2:
            return DriftPayload(nickname=nick, text=plain[:800])
        if isinstance(raw, str) and raw:
            url = first_http_image_url_from_cq_raw(raw)
            if url:
                data = await download_image_url(url)
                if data:
                    return DriftPayload(nickname=nick, image_bytes=data)
    return None


async def _pg_pick(bot_id: int, exclude_gid: int | None) -> DriftPayload | None:
    from sqlalchemy import func, select

    from src.common.db.repository_pg import MessageRow, get_session

    now = int(time.time())
    cutoff = now - _HISTORY_MAX_AGE_SEC
    try:
        async with get_session() as session:
            stmt = (
                select(MessageRow.plain_text, MessageRow.keywords, MessageRow.raw_message)
                .where(MessageRow.bot_id == bot_id)
                .where(MessageRow.time >= cutoff)
                .where(MessageRow.keywords.startswith(DREAM_KEY_PREFIX))
            )
            if exclude_gid is not None:
                stmt = stmt.where(MessageRow.group_id != exclude_gid)
            r = await session.execute(stmt.order_by(func.random()).limit(16))
            rows = list(r.all())
    except Exception as e:
        logger.debug("history_bottle pg query failed: {}", e)
        return None
    random.shuffle(rows)
    for plain, keywords, raw in rows:
        kw = keywords or ""
        nick = dream_display_name_from_keywords(kw if isinstance(kw, str) else "")
        p = (plain or "").strip()
        rs = raw or ""
        if len(p) >= 2:
            return DriftPayload(nickname=nick, text=p[:800])
        if isinstance(rs, str) and rs:
            url = first_http_image_url_from_cq_raw(rs)
            if url:
                data = await download_image_url(url)
                if data:
                    return DriftPayload(nickname=nick, image_bytes=data)
    return None
