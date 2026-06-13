"""本机语料渐进同步到社区共享池。"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from nonebot import logger

from src.features.corpus.backfill_store import load_backfill_state, save_backfill_state
from src.features.corpus.config import community_contribute_enabled, get_corpus_config
from src.features.corpus.factory import build_community_repository
from src.features.corpus.store import corpus_community_enrollment_valid
from src.features.corpus.text_util import plain_message_text
from src.features.corpus.write_fanout import corpus_write_queue
from src.platform.bot_runtime.roles import is_sharded_worker

if TYPE_CHECKING:
    from src.foundation.db.modules import Context


def corpus_backfill_enabled() -> bool:
    from src.foundation.config.repo_settings import repo_env_raw_value

    raw = repo_env_raw_value("PALLAS_CORPUS_BACKFILL_ENABLED")
    if raw is None:
        return False
    return str(raw).strip().lower() not in ("0", "false", "no", "off")


def corpus_backfill_batch_size() -> int:
    from src.foundation.config.repo_settings import repo_env_raw_value

    raw = repo_env_raw_value("PALLAS_CORPUS_BACKFILL_BATCH_SIZE")
    try:
        return max(1, min(int(str(raw or "30").strip()), 200))
    except ValueError:
        return 30


def corpus_backfill_interval_sec() -> int:
    from src.foundation.config.repo_settings import repo_env_raw_value

    raw = repo_env_raw_value("PALLAS_CORPUS_BACKFILL_INTERVAL_SEC")
    try:
        return max(300, min(int(str(raw or "1800").strip()), 86400))
    except ValueError:
        return 1800


def corpus_backfill_max_per_minute() -> int:
    from src.foundation.config.repo_settings import repo_env_raw_value

    raw = repo_env_raw_value("PALLAS_CORPUS_BACKFILL_MAX_PER_MINUTE")
    try:
        return max(1, min(int(str(raw or "40").strip()), 500))
    except ValueError:
        return 40


_rate_window_start = 0
_rate_window_count = 0


def should_run_corpus_backfill() -> bool:
    if is_sharded_worker():
        return False
    if not corpus_backfill_enabled():
        return False
    cfg = get_corpus_config()
    if not community_contribute_enabled(cfg):
        return False
    if not corpus_community_enrollment_valid():
        return False
    return build_community_repository() is not None


def backfill_should_skip_pressure() -> bool:
    from src.foundation.db.pool_budget import pg_pool_under_pressure

    if pg_pool_under_pressure(threshold=0.78):
        return True
    if corpus_write_queue().full():
        return True
    return False


def consume_backfill_rate_slot() -> bool:
    global _rate_window_start, _rate_window_count
    now = int(time.time())
    if now - _rate_window_start >= 60:
        _rate_window_start = now
        _rate_window_count = 0
    limit = corpus_backfill_max_per_minute()
    if _rate_window_count >= limit:
        return False
    _rate_window_count += 1
    return True


async def list_local_contexts_page(*, after_keywords: str, limit: int) -> list[Context]:
    backend = __import__("src.foundation.db", fromlist=["get_db_backend"]).get_db_backend()
    if backend == "postgresql":
        return await list_local_contexts_page_pg(after_keywords=after_keywords, limit=limit)
    if backend == "mongodb":
        return await list_local_contexts_page_mongo(after_keywords=after_keywords, limit=limit)
    return []


async def list_local_contexts_page_pg(*, after_keywords: str, limit: int) -> list[Context]:
    from sqlalchemy import select

    from src.foundation.db.repository_pg import ContextRow, get_session, row_to_context

    async with get_session(read_only=True) as session:
        stmt = select(ContextRow).order_by(ContextRow.keywords.asc()).limit(limit)
        if after_keywords:
            stmt = (
                select(ContextRow)
                .where(ContextRow.keywords > after_keywords)
                .order_by(ContextRow.keywords.asc())
                .limit(limit)
            )
        rows = (await session.execute(stmt)).scalars().all()
    return [row_to_context(row) for row in rows if row is not None]


async def list_local_contexts_page_mongo(*, after_keywords: str, limit: int) -> list[Context]:
    from src.foundation.db.modules import Context

    query: dict[str, Any] = {}
    if after_keywords:
        query["keywords"] = {"$gt": after_keywords}
    return await Context.find(query).sort("+keywords").limit(limit).to_list()


async def push_context_to_community(context: Context, community) -> int:
    pushed = 0
    for ans in context.answers or []:
        message = pick_backfill_message(ans.messages, ans.keywords)
        if not message:
            continue
        await community.upsert_answer(
            keywords=context.keywords,
            group_id=0,
            answer_keywords=ans.keywords,
            answer_time=int(ans.time or 0),
            message=message,
            append_on_existing=True,
        )
        pushed += 1
    return pushed


def pick_backfill_message(messages: list[str] | None, fallback: str) -> str:
    for raw in messages or []:
        text = plain_message_text(str(raw))
        if text:
            return text
    return plain_message_text(str(fallback or ""))


async def run_corpus_backfill_round() -> None:
    if not should_run_corpus_backfill():
        return
    if backfill_should_skip_pressure():
        logger.debug("corpus backfill skipped: pool pressure or mirror queue full")
        return

    community = build_community_repository()
    if community is None:
        return

    state = load_backfill_state()
    cursor = str(state.get("cursor_keywords") or "")
    batch_size = corpus_backfill_batch_size()
    contexts = await list_local_contexts_page(after_keywords=cursor, limit=batch_size)
    if not contexts:
        if cursor:
            save_backfill_state({"cursor_keywords": "", "wrapped_unix": int(time.time())})
            logger.info("corpus backfill round done pushed=0 skipped=0 cursor=wrapped")
        return

    pushed = 0
    skipped = 0
    last_keywords = cursor
    for context in contexts:
        if not consume_backfill_rate_slot():
            skipped += len(contexts) - pushed - skipped
            break
        if backfill_should_skip_pressure():
            skipped += 1
            continue
        try:
            pushed += await push_context_to_community(context, community)
        except Exception as e:
            skipped += 1
            logger.warning("corpus backfill item failed keywords={}: {}", context.keywords, e)
            continue
        last_keywords = context.keywords

    save_backfill_state({"cursor_keywords": last_keywords, "updated_unix": int(time.time())})
    logger.info(
        "corpus backfill round done pushed={} skipped={} cursor={}",
        pushed,
        skipped,
        last_keywords[:40],
    )
