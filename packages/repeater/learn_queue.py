"""复读学习 outbox producer：主路径只捕获并有界入队。"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from nonebot import get_driver, logger

from pallas.core.foundation.startup_report import register_startup_ready
from pallas.core.platform.multi_bot.group import claim_group_message_event
from pallas.core.platform.work_jobs.models import WorkJob
from pallas.core.platform.work_jobs.runtime import build_work_job_store

from .learn_runtime_config import get_repeater_learn_runtime_config

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from nonebot.adapters.onebot.v11 import GroupMessageEvent

    from .model import Chat

_LEARN_PLUGIN = "repeater_learn"
_queue: asyncio.Queue[WorkJob] | None = None
_message_queue: asyncio.Queue[WorkJob] | None = None
_sem: asyncio.Semaphore | None = None
_sem_limit: int | None = None
_worker_tasks: list[asyncio.Task[None]] = []
_learn_pool_wait_spins: int = 0
_LIFECYCLE_BOUND = False
_FLUSH_BATCH_SIZE = 64
_SHUTDOWN_DRAIN_SEC = 0.2


def drain_learn_pause_stats() -> int:
    global _learn_pool_wait_spins
    spins = _learn_pool_wait_spins
    _learn_pool_wait_spins = 0
    return spins


async def wait_pg_pool_headroom_for_learn() -> None:
    global _learn_pool_wait_spins
    from pallas.core.foundation.db.pool_budget import pg_pool_under_pressure

    while pg_pool_under_pressure(threshold=0.25):
        _learn_pool_wait_spins += 1
        await asyncio.sleep(0.2)


def learn_queue_pressure_threshold() -> int:
    """队列到达该水位时优先保护接话，跳过新增 learn。"""
    # learn 队列一旦堆高，后续还会连带压住 image cache / corpus prefetch
    # 这里提前刹车，让主循环更快恢复，而不是把回填吞吐吃满。
    return max(64, learn_queue_max_size() // 16)


def learn_concurrency() -> int:
    from pallas.core.foundation.db.pool_budget import pg_pool_capacity

    requested = get_repeater_learn_runtime_config().learn_concurrency
    # learn 会持续制造本地写入、cache invalidate 与镜像回填，实际比普通后台 IO 更容易拖慢主循环。
    # 0.03 比例在容量 ≤33 的池上会归零（20*0.03<1），下限提到 2 保证小池也能并行消化 outbox。
    ceiling = max(2, int(pg_pool_capacity() * 0.03))
    return max(1, min(int(requested), ceiling))


def learn_queue_max_size() -> int:
    return get_repeater_learn_runtime_config().learn_queue_max_size


def clear_repeater_learn_runtime_state() -> None:
    """清信号量/队列缓存；配合 WebUI 热重载或 worker 重启。"""
    global _queue, _message_queue, _sem, _sem_limit
    _sem = None
    _sem_limit = None
    _queue = None
    _message_queue = None


def learn_sem() -> asyncio.Semaphore:
    global _sem, _sem_limit
    limit = learn_concurrency()
    if _sem is None or _sem_limit != limit:
        _sem = asyncio.Semaphore(limit)
        _sem_limit = limit
    return _sem


def learn_queue() -> asyncio.Queue[WorkJob]:
    global _queue
    if _queue is None:
        _queue = asyncio.Queue(maxsize=learn_queue_max_size())
    return _queue


def message_queue() -> asyncio.Queue[WorkJob]:
    """message 落库独立队列，与 learn 共享 worker 但消费优先。"""
    global _message_queue
    if _message_queue is None:
        _message_queue = asyncio.Queue(maxsize=learn_queue_max_size())
    return _message_queue


def learn_queue_under_pressure() -> bool:
    return learn_queue().qsize() >= learn_queue_pressure_threshold()


def should_skip_repeater_learn_enqueue() -> bool:
    from pallas.core.foundation.db.pool_budget import pg_pool_under_pressure
    from pallas.core.platform.ingress.message_load import should_shed_chat_sidework

    if should_shed_chat_sidework():
        return True
    if pg_pool_under_pressure(threshold=0.25):
        return True
    return learn_queue_under_pressure()


def is_nul_payload_error(exc: Exception) -> bool:
    return "\\u0000 cannot be converted to text" in str(exc)


async def run_learn_consumer() -> None:
    while True:
        first = await _next_outbox_job()
        jobs = [first]
        try:
            while len(jobs) < _FLUSH_BATCH_SIZE:
                try:
                    jobs.append(_next_outbox_job_nowait())
                except asyncio.QueueEmpty:
                    break
            await wait_pg_pool_headroom_for_learn()
            await build_work_job_store().enqueue_many(jobs)
            from pallas.core.platform.ingress.hotpath_metrics import record_learn_persisted

            record_learn_persisted(len(jobs))
        except asyncio.CancelledError:
            from pallas.core.platform.ingress.hotpath_metrics import record_learn_dropped_shutdown

            record_learn_dropped_shutdown(len(jobs))
            raise
        except Exception as exc:
            logger.warning("Repeater learn outbox batch failed for [{}] jobs: [{}]", len(jobs), exc)
            if is_nul_payload_error(exc):
                logger.warning("Repeater learn outbox dropped NUL payloads for [{}] jobs", len(jobs))
                continue
            while True:
                await asyncio.sleep(0.2)
                try:
                    await build_work_job_store().enqueue_many(jobs)
                except Exception as retry_exc:
                    logger.warning("Repeater learn outbox batch retry failed for [{}] jobs: [{}]", len(jobs), retry_exc)
                    continue
                from pallas.core.platform.ingress.hotpath_metrics import record_learn_persisted

                record_learn_persisted(len(jobs))
                break
        finally:
            for _job in jobs:
                _source_queue_for(_job).task_done()


async def _next_outbox_job() -> WorkJob:
    """message 队列优先；为空时再取 learn 队列。"""
    try:
        return message_queue().get_nowait()
    except asyncio.QueueEmpty:
        return await learn_queue().get()


def _next_outbox_job_nowait() -> WorkJob:
    try:
        return message_queue().get_nowait()
    except asyncio.QueueEmpty:
        return learn_queue().get_nowait()


def _source_queue_for(job: WorkJob) -> asyncio.Queue[WorkJob]:
    """按 job 归属找源队列，确保 task_done 落在正确队列。"""
    if job.kind == "repeater.message":
        return message_queue()
    return learn_queue()


async def enqueue_repeater_learn(chat: Chat, event: GroupMessageEvent) -> bool:
    """抢占成功后先保证 message 落库，再按压力保护入队 learn。"""
    if not await claim_group_message_event(_LEARN_PLUGIN, event, int(event.self_id)):
        return False
    observe_quoted_semantic_style_feedback(event)

    from .learner import Learner

    message_dict = await Learner.capture_message_for_persist(chat.chat_data)
    if message_dict is not None:
        enqueue_message_persist_job(message_dict, event)
    if should_skip_repeater_learn_enqueue():
        from pallas.core.platform.ingress.hotpath_metrics import record_learn_skipped_pressure

        record_learn_skipped_pressure()
        return False
    from .model import Chat

    payload = await Learner.capture_for_work(chat.chat_data, Chat._topics_lock, Chat._recent_topics)
    if payload is None:
        return False
    job = WorkJob.create(
        kind="repeater.learn",
        payload=payload.to_dict(),
        idempotency_key=f"repeater.learn:{int(event.group_id)}:{int(event.message_id)}:{int(event.self_id)}",
    )
    try:
        learn_queue().put_nowait(job)
    except asyncio.QueueFull:
        from pallas.core.platform.ingress.hotpath_metrics import record_learn_skipped_full

        record_learn_skipped_full()
        return False
    semantic_job = build_semantic_style_job(payload.to_dict(), event)
    if semantic_job is not None:
        try:
            learn_queue().put_nowait(semantic_job)
        except asyncio.QueueFull:
            logger.debug("repeater semantic style enqueue skipped: queue full")
    from pallas.core.platform.ingress.hotpath_metrics import record_learn_buffered, record_learn_enqueued

    record_learn_enqueued()
    record_learn_buffered()
    return True


def enqueue_message_persist_job(message_dict: dict[str, object], event: GroupMessageEvent) -> bool:
    """message 落库独立于 learn 压力：进独立队列，由同一批 worker 优先消费。"""
    job = WorkJob.create(
        kind="repeater.message",
        payload={"message": message_dict},
        idempotency_key=f"repeater.message:{int(event.group_id)}:{int(event.message_id)}",
    )
    try:
        message_queue().put_nowait(job)
    except asyncio.QueueFull:
        from pallas.core.platform.ingress.hotpath_metrics import record_message_persist_skipped_full

        record_message_persist_skipped_full()
        return False
    from pallas.core.platform.ingress.hotpath_metrics import record_message_persist_buffered

    record_message_persist_buffered()
    return True


def observe_quoted_semantic_style_feedback(event: GroupMessageEvent) -> object | None:
    replied_message_id = 0
    for segment in getattr(event, "message", ()):
        if segment.type == "reply" and str(segment.data.get("id") or "").isdigit():
            replied_message_id = int(segment.data["id"])
            break
    if replied_message_id <= 0:
        return
    from pallas.product.llm.repeater_feedback import record_quoted_semantic_style_feedback

    return record_quoted_semantic_style_feedback(
        bot_id=int(event.self_id),
        group_id=int(event.group_id),
        replied_bot_message_id=replied_message_id,
        following_created_at=int(event.time),
        following_user_id=int(event.user_id),
        following_text=str(event.get_plaintext() or "").strip(),
    )


def build_semantic_style_job(payload: dict[str, object], event: GroupMessageEvent) -> WorkJob | None:
    """关系学习已入队后，附带一份可随压力丢弃的标注任务。"""
    chat = payload.get("chat")
    predecessor = payload.get("predecessor")
    if not isinstance(chat, dict) or not isinstance(predecessor, dict):
        return None
    trigger = str(predecessor.get("plain_text") or predecessor.get("raw_message") or "").strip()
    reply = str(chat.get("plain_text") or chat.get("raw_message") or "").strip()
    if not trigger or not reply:
        return None
    group_id = int(chat.get("group_id") or 0)
    bot_id = int(chat.get("bot_id") or 0)
    if group_id <= 0 or bot_id <= 0:
        return None
    from pallas.product.llm.repeater_semantic_style import (
        claim_semantic_style_realtime_admission,
        is_human_semantic_style_pair,
        semantic_style_collection_enabled,
    )

    trigger_user_id = int(predecessor.get("user_id") or 0)
    reply_user_id = int(chat.get("user_id") or 0)
    if not is_human_semantic_style_pair(
        trigger_user_id=trigger_user_id,
        reply_user_id=reply_user_id,
        bot_id=bot_id,
    ):
        return None
    if not semantic_style_collection_enabled(bot_id=bot_id, group_id=group_id):
        return None
    predecessor_message_id = int(predecessor.get("message_id") or 0)
    reply_to_message_id = int(chat.get("reply_to_message_id") or 0)
    pair_relation = "quoted" if predecessor_message_id and reply_to_message_id == predecessor_message_id else "adjacent"
    example_id = f"{group_id}:{int(event.message_id)}:{bot_id}"
    if not claim_semantic_style_realtime_admission(bot_id=bot_id, group_id=group_id, example_id=example_id):
        return None
    return WorkJob.create(
        kind="repeater.semantic_style",
        payload={
            "example_id": example_id,
            "message_id": int(event.message_id),
            "created_at": int(chat.get("time") or 0),
            "bot_id": bot_id,
            "group_id": group_id,
            "scene": "group_chat",
            "trigger_text": trigger,
            "reply_text": reply,
            "source_kind": "human_pair",
            "trigger_user_id": trigger_user_id,
            "reply_user_id": reply_user_id,
            "pair_relation": pair_relation,
            "realtime_admitted": True,
        },
        idempotency_key=f"repeater.semantic_style:{group_id}:{int(event.message_id)}:{bot_id}",
    )


def build_semantic_style_backfill_batch(
    candidates: Iterable[Mapping[str, object]],
    *,
    cursor: object | None = None,
    now: int | None = None,
    remaining_today: int | None = None,
):
    """历史候选仅在实时 learn 队列清空后入队，避免抢占新接话标注。"""
    from pallas.product.llm.repeater_semantic_style import SemanticStyleBackfillCursor
    from pallas.product.llm.repeater_semantic_style import build_semantic_style_backfill_batch as build_batch

    resolved_cursor = cursor if isinstance(cursor, SemanticStyleBackfillCursor) else SemanticStyleBackfillCursor()
    return build_batch(
        candidates,
        cursor=resolved_cursor,
        now=now,
        remaining_today=remaining_today,
        has_pending_new_jobs=not learn_queue().empty(),
    )


def enqueue_semantic_style_backfill_jobs(jobs: Iterable[WorkJob]) -> int:
    """已排程的历史任务只填充实时队列空档。"""
    if not learn_queue().empty():
        return 0
    queued = 0
    for job in jobs:
        try:
            learn_queue().put_nowait(job)
        except asyncio.QueueFull:
            break
        queued += 1
    return queued


def _learn_workers_running() -> bool:
    return bool(_worker_tasks) and any(not t.done() for t in _worker_tasks)


async def start_repeater_learn_worker() -> None:
    global _worker_tasks
    if _learn_workers_running():
        return
    await stop_repeater_learn_worker()
    _worker_tasks = [
        asyncio.create_task(run_learn_consumer(), name=f"repeater_learn_outbox_writer:{index}")
        for index in range(learn_concurrency())
    ]
    logger.debug(
        "repeater learn outbox writer started: queue_max={} workers={}",
        learn_queue_max_size(),
        len(_worker_tasks),
    )


def discard_buffered_repeater_jobs() -> None:
    dropped = 0
    for source in (message_queue(), learn_queue()):
        while True:
            try:
                source.get_nowait()
            except asyncio.QueueEmpty:
                break
            source.task_done()
            dropped += 1
    if dropped:
        from pallas.core.platform.ingress.hotpath_metrics import record_learn_dropped_shutdown

        record_learn_dropped_shutdown(dropped)


async def stop_repeater_learn_worker() -> None:
    global _worker_tasks
    tasks = list(_worker_tasks)
    _worker_tasks = []
    if tasks:
        try:
            await asyncio.wait_for(
                asyncio.gather(message_queue().join(), learn_queue().join()), timeout=_SHUTDOWN_DRAIN_SEC
            )
        except TimeoutError:
            pass
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    discard_buffered_repeater_jobs()


async def reload_repeater_learn_worker_runtime() -> None:
    """WebUI 保存 learn 配置后：失效缓存并重启 worker。"""
    from .learn_runtime_config import clear_repeater_learn_runtime_config_cache

    await stop_repeater_learn_worker()
    clear_repeater_learn_runtime_config_cache()
    clear_repeater_learn_runtime_state()
    await start_repeater_learn_worker()
    logger.info(
        "repeater learn runtime reloaded: queue_max={}",
        learn_queue_max_size(),
    )


def bind_repeater_learn_lifecycle() -> None:
    global _LIFECYCLE_BOUND
    if _LIFECYCLE_BOUND:
        return
    _LIFECYCLE_BOUND = True
    driver = get_driver()

    @driver.on_startup
    async def _on_startup():
        from .model import warmup_keyword_extraction

        await asyncio.to_thread(warmup_keyword_extraction)
        await start_repeater_learn_worker()
        register_startup_ready(
            "复读学习队列",
            f"worker [{len(_worker_tasks)}] | 队列上限 [{learn_queue_max_size()}]",
        )

    @driver.on_shutdown
    async def _on_shutdown():
        await stop_repeater_learn_worker()
