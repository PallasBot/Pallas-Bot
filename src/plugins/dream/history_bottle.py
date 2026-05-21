from __future__ import annotations

import asyncio
import random
import re
import time
import urllib.parse
from collections import OrderedDict
from dataclasses import dataclass
from typing import Literal

from nonebot import get_bots, logger

from src.common.db import get_db_backend

from .config import plugin_config
from .dedupe_keys import dream_image_dedupe_key, dream_text_dedupe_key
from .http_utils import download_image_url
from .payload import DriftPayload

# 写入 message.keywords 的前缀（与复读侧 keywords 区分）
DREAM_KEY_PREFIX = "is_dream"
DREAM_RECORD_SEP = "\x1e"

_HIST_SAMPLE_SIZE = 28

# 按「接收梦话的群」隔离：本群近期已发过的历史键，不影响其它群抽样
_recent_drift_keys_by_group: dict[int, OrderedDict[str, None]] = {}
_recent_lock = asyncio.Lock()


def _history_cutoff_ts(now: int) -> int:
    days = max(7, int(plugin_config.dream_message_retention_days))
    return now - days * 86400


def _recency_weight(t: int, *, cutoff: int, now: int, power: float) -> float:
    if power <= 0:
        return 1.0
    span = max(1, now - cutoff)
    rel = (t - cutoff) / span
    rel = max(0.0, min(1.0, rel))
    return (rel + 0.06) ** power


def _weighted_pick_index(weights: list[float]) -> int:
    adj = [max(1e-12, w) for w in weights]
    total = sum(adj)
    r = random.uniform(0, total)
    acc = 0.0
    for i, w in enumerate(adj):
        acc += w
        if r <= acc:
            return i
    return len(adj) - 1


async def register_recent_drift_dedupe_key(group_id: int, key: str) -> None:
    if not key:
        return
    maxn = int(plugin_config.dream_history_recent_dedupe_max)
    if maxn <= 0:
        return
    async with _recent_lock:
        od = _recent_drift_keys_by_group.setdefault(int(group_id), OrderedDict())
        if key in od:
            od.move_to_end(key)
        od[key] = None
        while len(od) > maxn:
            od.popitem(last=False)


async def _recent_drift_exclude_keys(group_id: int) -> set[str]:
    if int(plugin_config.dream_history_recent_dedupe_max) <= 0:
        return set()
    async with _recent_lock:
        od = _recent_drift_keys_by_group.get(int(group_id))
        if not od:
            return set()
        return set(od.keys())


@dataclass(slots=True)
class _HistPick:
    kind: Literal["text", "img"]
    time: int
    nickname: str
    text: str | None = None
    image_url: str | None = None


def _build_hist_pick_from_fields(time_v: int, keywords: str, plain: str, raw: str) -> _HistPick | None:
    nick = dream_display_name_from_keywords(keywords if isinstance(keywords, str) else "")
    p = (plain or "").strip()
    rs = raw or ""
    if len(p) >= 2:
        return _HistPick(kind="text", time=time_v, nickname=nick, text=p)
    if isinstance(rs, str) and rs:
        url = first_http_image_url_from_cq_raw(rs)
        if url:
            return _HistPick(kind="img", time=time_v, nickname=nick, image_url=url)
    return None


async def _pick_payload_from_cands(
    cands: list[_HistPick],
    exclude: set[str],
    *,
    cutoff: int,
    now: int,
    power: float,
) -> DriftPayload | None:
    if not cands:
        return None
    filtered: list[_HistPick] = []
    for c in cands:
        if c.kind == "text" and c.text:
            if dream_text_dedupe_key(c.text) not in exclude:
                filtered.append(c)
        else:
            filtered.append(c)
    use = filtered or cands
    pool = list(range(len(use)))
    max_tries = min(16, max(1, len(use) * 2))
    for _ in range(max_tries):
        if not pool:
            break
        ws = [_recency_weight(use[i].time, cutoff=cutoff, now=now, power=power) for i in pool]
        rj = _weighted_pick_index(ws)
        idx = pool.pop(rj)
        c = use[idx]
        if c.kind == "text" and c.text:
            return DriftPayload(nickname=c.nickname, text=c.text[:800])
        if c.kind == "img" and c.image_url:
            data = await download_image_url(c.image_url)
            if not data:
                continue
            ik = dream_image_dedupe_key(data)
            if ik in exclude and pool:
                continue
            return DriftPayload(nickname=c.nickname, image_bytes=data)
    return None


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


def dream_history_bot_ids(process_fallback_self_id: int) -> list[int]:
    """参与历史梦库采样的牛牛 QQ；分片时为全集群在线 catalog，单进程为本进程连接。"""
    from src.common.shard.registry.config import is_sharding_active

    if is_sharding_active():
        from src.common.multi_bot.fleet import get_catalog_bot_ids
        from src.common.shard.presence import get_cluster_online_bot_ids

        ids = set(get_catalog_bot_ids()) & set(get_cluster_online_bot_ids())
    else:
        try:
            ids = {int(b.self_id) for b in get_bots().values()}
        except Exception:
            ids = set()
    if not ids:
        return [process_fallback_self_id]
    ids.add(process_fallback_self_id)
    return sorted(ids)


async def sample_historical_drift(
    *, bot_id: int, consumer_group_id: int, exclude_group_id: int | None = None
) -> DriftPayload | None:
    bot_ids = dream_history_bot_ids(bot_id)
    backend = get_db_backend()
    exclude_send = await _recent_drift_exclude_keys(int(consumer_group_id))
    if backend == "mongodb":
        return await _mongo_pick(bot_ids, exclude_group_id, exclude_send)
    if backend == "postgresql":
        return await _pg_pick(bot_ids, exclude_group_id, exclude_send)
    return None


async def _mongo_pick(bot_ids: list[int], exclude_gid: int | None, exclude_send: set[str]) -> DriftPayload | None:
    from src.common.db.modules import Message

    coll = Message.get_pymongo_collection()
    now = int(time.time())
    cutoff = _history_cutoff_ts(now)
    key_pat = f"^{re.escape(DREAM_KEY_PREFIX)}"
    match: dict = {
        "keywords": {"$regex": key_pat},
        "bot_id": {"$in": bot_ids},
        "time": {"$gte": cutoff},
    }
    if exclude_gid is not None:
        match["group_id"] = {"$ne": exclude_gid}
    pipeline = [
        {"$match": match},
        {"$sample": {"size": _HIST_SAMPLE_SIZE}},
    ]
    try:
        docs = [d async for d in coll.aggregate(pipeline)]
    except Exception as e:
        logger.debug(f"bot [{bot_ids[0]}] dream history sample mongo aggregate failed: {e}")
        return None
    cands: list[_HistPick] = []
    for doc in docs:
        kw = doc.get("keywords") or ""
        tv = int(doc.get("time") or 0)
        plain = (doc.get("plain_text") or "").strip()
        raw = doc.get("raw_message") or ""
        hp = _build_hist_pick_from_fields(
            tv,
            kw if isinstance(kw, str) else "",
            plain,
            raw if isinstance(raw, str) else "",
        )
        if hp is not None:
            cands.append(hp)
    power = float(plugin_config.dream_history_recency_power)
    try:
        return await _pick_payload_from_cands(cands, exclude_send, cutoff=cutoff, now=now, power=power)
    except Exception as e:
        logger.debug(f"bot [{bot_ids[0]}] dream history sample mongo pick failed: {e}")
        return None


async def _pg_pick(bot_ids: list[int], exclude_gid: int | None, exclude_send: set[str]) -> DriftPayload | None:
    from sqlalchemy import func, select

    from src.common.db.repository_pg import MessageRow, get_session

    now = int(time.time())
    cutoff = _history_cutoff_ts(now)
    power = float(plugin_config.dream_history_recency_power)
    try:
        async with get_session() as session:
            stmt = (
                select(MessageRow.time, MessageRow.plain_text, MessageRow.keywords, MessageRow.raw_message)
                .where(MessageRow.bot_id.in_(bot_ids))
                .where(MessageRow.time >= cutoff)
                .where(MessageRow.keywords.startswith(DREAM_KEY_PREFIX))
            )
            if exclude_gid is not None:
                stmt = stmt.where(MessageRow.group_id != exclude_gid)
            r = await session.execute(stmt.order_by(func.random()).limit(_HIST_SAMPLE_SIZE))
            rows = list(r.all())
    except Exception as e:
        logger.debug(f"bot [{bot_ids[0]}] dream history sample pg query failed: {e}")
        return None
    cands: list[_HistPick] = []
    for tv, plain, keywords, raw in rows:
        hp = _build_hist_pick_from_fields(int(tv or 0), keywords or "", plain or "", raw or "")
        if hp is not None:
            cands.append(hp)
    try:
        return await _pick_payload_from_cands(cands, exclude_send, cutoff=cutoff, now=now, power=power)
    except Exception as e:
        logger.debug(f"bot [{bot_ids[0]}] dream history sample pg pick failed: {e}")
        return None
