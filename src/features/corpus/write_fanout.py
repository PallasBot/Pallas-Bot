"""学习写入后异步 mirror 到联邦 / 社区语料源。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from nonebot import get_driver, logger

from src.features.corpus.config import CorpusConfig, community_contribute_enabled
from src.foundation.db.modules import Answer, Context

if TYPE_CHECKING:
    from src.foundation.db.repository import ContextRepository


def community_mirror_context(context: Context) -> Context:

    answers = [
        Answer(
            keywords=a.keywords,
            group_id=0,
            count=int(a.count),
            time=int(a.time),
            messages=list(a.messages),
        )
        for a in (context.answers or [])
    ]
    return Context.model_construct(
        keywords=context.keywords,
        time=int(context.time),
        trigger_count=int(context.trigger_count),
        answers=answers,
        ban=list(context.ban or []),
        clear_time=int(context.clear_time),
    )


_WRITE_QUEUE_MAX = 2048
_write_queue: asyncio.Queue[_MirrorWriteOp] | None = None
_write_tasks: list[asyncio.Task[None]] = []
_write_dropped_full: int = 0
_LIFECYCLE_BOUND = False


@dataclass(frozen=True)
class _MirrorWriteOp:
    kind: Literal["upsert_answer", "insert"]
    payload: dict[str, Any]


def corpus_write_queue() -> asyncio.Queue[_MirrorWriteOp]:
    global _write_queue
    if _write_queue is None:
        _write_queue = asyncio.Queue(maxsize=_WRITE_QUEUE_MAX)
    return _write_queue


def clear_corpus_write_runtime_state() -> None:
    global _write_queue
    _write_queue = None


def corpus_write_concurrency() -> int:
    # 社区写回不在热路径，固定单 worker 避免 create_task 风暴反压事件循环。
    return 1


def _write_workers_running() -> bool:
    return bool(_write_tasks) and any(not task.done() for task in _write_tasks)


async def run_corpus_write_consumer() -> None:
    while True:
        op = await corpus_write_queue().get()
        try:
            if op.kind == "upsert_answer":
                await mirror_upsert_answer(**op.payload)
            else:
                await mirror_insert(**op.payload)
        except Exception as e:
            logger.warning("corpus mirror failed: {}", e)
        finally:
            corpus_write_queue().task_done()


async def start_corpus_write_workers() -> None:
    global _write_tasks
    if _write_workers_running():
        return
    await stop_corpus_write_workers()
    n = corpus_write_concurrency()
    _write_tasks = [
        asyncio.create_task(run_corpus_write_consumer(), name=f"corpus_write_consumer_{i}") for i in range(n)
    ]


async def stop_corpus_write_workers() -> None:
    global _write_tasks
    if not _write_tasks:
        return
    tasks = list(_write_tasks)
    _write_tasks = []
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


def ensure_corpus_write_workers() -> None:
    bind_corpus_write_lifecycle()
    if _write_workers_running():
        return
    asyncio.create_task(start_corpus_write_workers())


def bind_corpus_write_lifecycle() -> None:
    global _LIFECYCLE_BOUND
    if _LIFECYCLE_BOUND:
        return
    _LIFECYCLE_BOUND = True
    driver = get_driver()

    @driver.on_shutdown
    async def _on_shutdown() -> None:
        await stop_corpus_write_workers()


async def mirror_upsert_answer(
    *,
    fed: ContextRepository | None,
    community: ContextRepository | None,
    cfg: CorpusConfig,
    keywords: str,
    group_id: int,
    answer_keywords: str,
    answer_time: int,
    message: str,
    append_on_existing: bool,
) -> None:
    if cfg.fed_contribute and fed is not None:
        await fed.upsert_answer(
            keywords=keywords,
            group_id=group_id,
            answer_keywords=answer_keywords,
            answer_time=answer_time,
            message=message,
            append_on_existing=append_on_existing,
        )
    if community_contribute_enabled(cfg) and community is not None:
        await community.upsert_answer(
            keywords=keywords,
            group_id=0,
            answer_keywords=answer_keywords,
            answer_time=answer_time,
            message=message,
            append_on_existing=append_on_existing,
        )


async def mirror_insert(
    *,
    fed: ContextRepository | None,
    community: ContextRepository | None,
    cfg: CorpusConfig,
    context: Context,
) -> None:
    if cfg.fed_contribute and fed is not None:
        await fed.insert(context)
    if community_contribute_enabled(cfg) and community is not None:
        await community.insert(community_mirror_context(context))


def _enqueue_corpus_write(op: _MirrorWriteOp) -> None:
    global _write_dropped_full
    ensure_corpus_write_workers()
    try:
        corpus_write_queue().put_nowait(op)
    except asyncio.QueueFull:
        _write_dropped_full += 1
        if _write_dropped_full == 1 or _write_dropped_full % 200 == 0:
            logger.info(
                "corpus mirror queue full (max={}), dropped={}",
                _WRITE_QUEUE_MAX,
                _write_dropped_full,
            )


def schedule_mirror_upsert_answer(
    *,
    fed: ContextRepository | None,
    community: ContextRepository | None,
    cfg: CorpusConfig,
    keywords: str,
    group_id: int,
    answer_keywords: str,
    answer_time: int,
    message: str,
    append_on_existing: bool,
) -> None:
    if not cfg.fed_contribute and not community_contribute_enabled(cfg):
        return
    from src.foundation.db.pool_budget import pg_pool_under_pressure

    if pg_pool_under_pressure(threshold=0.78):
        from src.foundation.db.pool_diagnostics import note_mirror_skipped_pressure

        note_mirror_skipped_pressure()
        return
    _enqueue_corpus_write(
        _MirrorWriteOp(
            kind="upsert_answer",
            payload={
                "fed": fed,
                "community": community,
                "cfg": cfg,
                "keywords": keywords,
                "group_id": group_id,
                "answer_keywords": answer_keywords,
                "answer_time": answer_time,
                "message": message,
                "append_on_existing": append_on_existing,
            },
        )
    )


def schedule_mirror_insert(
    *,
    fed: ContextRepository | None,
    community: ContextRepository | None,
    cfg: CorpusConfig,
    context: Context,
) -> None:
    if not cfg.fed_contribute and not community_contribute_enabled(cfg):
        return
    from src.foundation.db.pool_budget import pg_pool_under_pressure

    if pg_pool_under_pressure(threshold=0.78):
        from src.foundation.db.pool_diagnostics import note_mirror_skipped_pressure

        note_mirror_skipped_pressure()
        return
    _enqueue_corpus_write(
        _MirrorWriteOp(
            kind="insert",
            payload={
                "fed": fed,
                "community": community,
                "cfg": cfg,
                "context": context,
            },
        )
    )


async def reset_corpus_write_runtime_state_for_tests() -> None:
    global _write_dropped_full
    await stop_corpus_write_workers()
    clear_corpus_write_runtime_state()
    _write_dropped_full = 0
