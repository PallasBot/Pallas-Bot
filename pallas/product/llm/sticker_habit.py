"""群友表情包使用习惯沉淀：扫描群消息里的图片发送，跨阈值后投影为人物事实。

链路：``message.raw_message`` 的 CQ:image 码（与采集同源截断）join ``image_cache``
拿 ``content_hash``，按 ``(group_id, user_id, content_hash)`` 累加进
``user_sticker_stat``；跨过 ``llm_sticker_habit_min_count`` 的最爱表情包借
``sticker_label`` 的 caption 写成 ``source="sticker_habit"`` 的人物事实，经
现有 person facts 注入块自动可见。send_count 语义是「可归因发送次数下界」：
capture 超时丢弃、下载失败、缓存周期清理造成的漏计可接受。
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import replace
from typing import TYPE_CHECKING

from nonebot import get_driver, logger

from pallas.core.foundation.db import (
    make_image_cache_repository,
    make_message_repository,
    make_sticker_label_repository,
    make_user_sticker_stat_repository,
)
from pallas.core.foundation.fs_lock import atomic_write_text
from pallas.core.foundation.startup_report import register_startup_scheduled
from pallas.product.llm.memory.person_facts import (
    forget_person_facts_by_source,
    replace_person_fact_by_source,
)
from pallas.product.llm.sender_identity import sender_kind

if TYPE_CHECKING:
    from pathlib import Path

STICKER_HABIT_SCAN_INTERVAL_SEC = 30 * 60
STICKER_HABIT_FACT_SOURCE = "sticker_habit"

_SCAN_ROWS_PER_GROUP_PASS = 2000
_ACTIVE_GROUP_WINDOW_SEC = 7 * 24 * 60 * 60
_CURSOR_STALE_SEC = 3 * 24 * 60 * 60
_CANDIDATES_PER_GROUP = 5
_LABEL_ENQUEUE_PER_GROUP = 20
_LABEL_ENQUEUE_GLOBAL_PER_PASS = 50
_MAX_FACT_LEN = 64
_MAX_TOP_K = 3
_PRUNE_MAX_COUNT = 2
_PRUNE_AFTER_DAYS = 90

_STICKER_HABIT_LIFECYCLE_BOUND = False


def extract_image_cq_codes(raw_message: str) -> list[str]:
    """从消息原文提取规范化的图片 CQ 码（与采集路径同源，勿另写截断正则）。"""
    if "[CQ:image" not in raw_message:
        return []
    from nonebot.adapters.onebot.v11 import Message

    from pallas.core.shared.utils.media_cache import normalize_image_cq_code

    codes: list[str] = []
    for segment in Message(raw_message):
        if segment.type != "image":
            continue
        code = normalize_image_cq_code(segment)
        if code:
            codes.append(code)
    return codes


def _sticker_habit_base_dir() -> Path:
    from pallas.product.llm.memory.ops import _data_dir

    return _data_dir() / "sticker_habit"


def _sticker_habit_cursor_path() -> Path:
    return _sticker_habit_base_dir() / "group_cursors.json"


def _load_sticker_habit_cursors() -> dict[int, tuple[int, int]]:
    try:
        raw = json.loads(_sticker_habit_cursor_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    cursors: dict[int, tuple[int, int]] = {}
    for key, value in raw.items():
        try:
            group_id = int(key)
        except (TypeError, ValueError):
            continue
        if isinstance(value, list) and len(value) == 2:
            try:
                cursors[group_id] = (int(value[0]), int(value[1]))
            except (TypeError, ValueError):
                continue
    return cursors


def _save_sticker_habit_cursors(cursors: dict[int, tuple[int, int]]) -> None:
    payload = {str(group_id): [cursor[0], cursor[1]] for group_id, cursor in cursors.items()}
    atomic_write_text(
        _sticker_habit_cursor_path(),
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n",
    )


def _initial_sticker_habit_cursor(now_ts: int) -> tuple[int, int]:
    from pallas.product.llm.config import get_llm_config

    days = max(0, min(int(getattr(get_llm_config(), "llm_sticker_habit_backfill_days", 7) or 0), 90))
    return (now_ts - days * 86400, 0)


async def _active_group_ids(repo, *, now_ts: int, cursors: dict[int, tuple[int, int]]) -> set[int]:
    from nonebot import get_bots

    group_ids: set[int] = set(cursors.keys())
    cutoff = now_ts - _ACTIVE_GROUP_WINDOW_SEC
    for bot in get_bots().values():
        try:
            bot_id = int(getattr(bot, "self_id", 0) or 0)
        except (TypeError, ValueError):
            continue
        if bot_id <= 0:
            continue
        try:
            group_ids.update(await repo.list_recent_group_ids_for_bot(bot_id, since_time=cutoff, limit=128))
        except Exception as exc:
            logger.warning("表情包习惯扫描无法列出账号 [{}] 的活跃群：{}", bot_id, exc)
    return group_ids


async def _scan_group_messages(
    *,
    group_id: int,
    cursor: tuple[int, int],
    repo,
) -> tuple[tuple[int, int], list[tuple[int, str, int]], int]:
    """扫一个群的增量窗口，返回 (新游标, [(user_id, cq_code, 发送时间)], 扫描行数)。

    游标按 ``(time, message_id)`` 复合边界严格推进到最后扫过的行；同一条消息
    被多账号重复录制时 (time, message_id) 相同，靠游标比较天然去重。
    """
    last_key = (int(cursor[0]), int(cursor[1]))
    events: list[tuple[int, str, int]] = []
    scanned = 0
    while scanned < _SCAN_ROWS_PER_GROUP_PASS:
        batch_limit = min(500, _SCAN_ROWS_PER_GROUP_PASS - scanned)
        batch = await repo.list_group_messages_after(
            group_id, after_time=last_key[0], after_message_id=last_key[1], limit=batch_limit
        )
        if not batch:
            break
        for item in batch:
            row_time = int(getattr(item, "time", 0) or 0)
            message_id = int(getattr(item, "message_id", 0) or 0)
            key = (row_time, message_id)
            if key <= last_key:
                continue
            last_key = key
            scanned += 1
            raw = str(getattr(item, "raw_message", "") or "")
            if "[CQ:image" not in raw:
                continue
            user_id = int(getattr(item, "user_id", 0) or 0)
            if user_id <= 0 or sender_kind(user_id, self_bot_id=0) != "human":
                continue
            events.extend((user_id, code, row_time) for code in extract_image_cq_codes(raw))
        if len(batch) < batch_limit:
            break
    return last_key, events, scanned


async def _record_send_events(
    *,
    group_id: int,
    events: list[tuple[int, str, int]],
    stat_repo,
    image_repo,
) -> dict[tuple[int, str], list[int]]:
    """join image_cache 取 content_hash 并累加统计；返回 ((user, hash) -> [次数, 最近时间])。

    join 不到或 content_hash 为空的图直接跳过（下载失败/未采集），不阻塞统计。
    """
    hash_by_code: dict[str, str | None] = {}
    deltas: dict[tuple[int, str], list[int]] = {}
    for user_id, code, sent_at in events:
        if code not in hash_by_code:
            cache = await image_repo.find_by_cq_code(code)
            hash_by_code[code] = str(cache.content_hash) if cache is not None and cache.content_hash else None
        content_hash = hash_by_code[code]
        if not content_hash:
            continue
        bucket = deltas.setdefault((int(user_id), content_hash), [0, 0])
        bucket[0] += 1
        bucket[1] = max(bucket[1], int(sent_at))
    for (user_id, content_hash), (count, last_sent_at) in deltas.items():
        await stat_repo.increment(
            group_id=group_id, user_id=user_id, content_hash=content_hash, sent_at=last_sent_at, count=count
        )
    return deltas


async def _resolve_group_bot(group_id: int, cache: dict[int, int]) -> int:
    """解析群的画像归属账号（复用语义采集 bot 的解析约定），结果进程内缓存。"""
    if group_id in cache:
        return cache[group_id]
    from pallas.product.llm.group_insight_processor import _resolve_semantic_bot

    try:
        bot_id = int(await _resolve_semantic_bot(group_id) or 0)
    except Exception as exc:
        logger.warning("表情包习惯投影无法解析群 [{}] 的归属账号：{}", group_id, exc)
        bot_id = 0
    cache[group_id] = bot_id
    return bot_id


async def _enqueue_sticker_label_for_hash(content_hash: str) -> bool:
    """为跨阈值但未标注的图借用 realtime 标注链路优先补标（预算/熔断内）。"""
    from pallas.core.platform.work_jobs.models import WorkJob
    from pallas.core.platform.work_jobs.runtime import build_work_job_store
    from pallas.product.llm.sticker_label_jobs import (
        STICKER_LABEL_JOB_KIND,
        STICKER_LABEL_PROMPT_VERSION,
        StickerLabelSource,
        lazy_sticker_labels_paused,
        sticker_label_circuit_open,
        sticker_label_realtime_budget_ok,
    )
    from pallas.product.llm.task_metrics import record_bot_llm_task

    if lazy_sticker_labels_paused() or sticker_label_circuit_open() or not sticker_label_realtime_budget_ok():
        return False
    job = WorkJob.create(
        kind=STICKER_LABEL_JOB_KIND,
        payload={},
        idempotency_key=f"{STICKER_LABEL_JOB_KIND}:{content_hash}:{STICKER_LABEL_PROMPT_VERSION}",
    )
    job = replace(
        job,
        payload={
            "content_hash": content_hash,
            "source": StickerLabelSource.RECOMMENDED_CANDIDATE.value,
            "prompt_version": STICKER_LABEL_PROMPT_VERSION,
            "observation": {"state": "queued"},
        },
    )
    _job, reactivated = await build_work_job_store().requeue_terminal(job)
    record_bot_llm_task("sticker_label", "submit_ok" if reactivated else "background_coalesced")
    return bool(reactivated)


def _habit_fact_source(rank: int) -> str:
    """top-K 事实的键控 source：第 1 名沿用无后缀键，向后兼容 v1。"""
    return STICKER_HABIT_FACT_SOURCE if rank <= 1 else f"{STICKER_HABIT_FACT_SOURCE}:{rank}"


async def _project_group_habits(
    *,
    group_id: int,
    delta_pairs: set[tuple[int, str]],
    stat_repo,
    cfg,
    bot_cache: dict[int, int],
    label_quota: int,
) -> tuple[int, int]:
    """把跨阈值的最爱表情包投影为人物事实（每人最多 top_k 条）；返回 (写入事实数, 补标入队数)。

    投影输入 = 本轮有增量的键 ∪ 群内跨阈值候选（按群查询），按 user 取
    send_count 前 top_k；未标注的键主动借用 realtime 补标，下轮自愈。
    """
    min_count = max(1, int(getattr(cfg, "llm_sticker_habit_min_count", 5) or 1))
    top_k = max(1, min(int(getattr(cfg, "llm_sticker_habit_top_k", 1) or 1), _MAX_TOP_K))
    label_repo = make_sticker_label_repository()

    ranked: dict[int, list[tuple[int, str]]] = {}

    def _consider(user_id: int, content_hash: str, count: int) -> None:
        if count < min_count:
            return
        bucket = ranked.setdefault(int(user_id), [])
        if any(existing_hash == content_hash for _count, existing_hash in bucket):
            return
        bucket.append((int(count), content_hash))

    for user_id, content_hash in delta_pairs:
        stat = await stat_repo.get(group_id=group_id, user_id=user_id, content_hash=content_hash)
        if stat is not None:
            _consider(user_id, content_hash, int(stat.send_count))
    candidates = await stat_repo.list_group_candidates(
        group_id=group_id, min_count=min_count, limit=_CANDIDATES_PER_GROUP * top_k
    )
    for row in candidates:
        _consider(int(row.user_id), str(row.content_hash), int(row.send_count))
    if not ranked:
        return 0, 0

    bot_id = await _resolve_group_bot(group_id, bot_cache)
    facts = 0
    label_queued = 0
    label_cache: dict[str, object] = {}
    for user_id in sorted(ranked):
        entries = sorted(ranked[user_id], key=lambda item: (-item[0], item[1]))[:top_k]
        for rank, (_count, content_hash) in enumerate(entries, start=1):
            if content_hash not in label_cache:
                label_cache[content_hash] = await label_repo.get(content_hash)
            label = label_cache[content_hash]
            caption = str(getattr(label, "caption", "") or "").strip() if label is not None else ""
            if label is None or not bool(getattr(label, "is_sticker", False)) or not caption:
                # 未标注的才补标；已标注为非表情/无 caption 的图不进入习惯事实
                if label is None and label_quota > label_queued and await _enqueue_sticker_label_for_hash(content_hash):
                    label_queued += 1
                continue
            content = f"常用表情包：{caption}" if rank <= 1 else f"也常发表情包：{caption}"
            if bot_id > 0:
                replace_person_fact_by_source(
                    bot_id=bot_id,
                    group_id=group_id,
                    user_id=user_id,
                    source=_habit_fact_source(rank),
                    content=content[:_MAX_FACT_LEN],
                    confidence=0.8,
                )
                facts += 1
        if bot_id > 0 and len(entries) < _MAX_TOP_K:
            # 产出缩水（阈值/K 调整）时清理多余的键控事实
            forget_person_facts_by_source(
                bot_id=bot_id,
                group_id=group_id,
                user_id=user_id,
                sources=[_habit_fact_source(rank) for rank in range(len(entries) + 1, _MAX_TOP_K + 1)],
            )
    return facts, label_queued


async def run_sticker_habit_pass() -> dict[str, int]:
    """扫描一轮群消息图片发送，沉淀统计与画像事实；返回计数摘要。"""
    from pallas.product.llm.config import get_llm_config

    cfg = get_llm_config()
    if not bool(getattr(cfg, "llm_sticker_habit_enabled", True)):
        return {"groups": 0, "messages": 0, "images": 0, "facts": 0, "label_queued": 0}

    repo = make_message_repository()
    stat_repo = make_user_sticker_stat_repository()
    image_repo = make_image_cache_repository()
    now_ts = int(time.time())
    cursors = _load_sticker_habit_cursors()
    initial_cursor = _initial_sticker_habit_cursor(now_ts)
    group_ids = await _active_group_ids(repo, now_ts=now_ts, cursors=cursors)

    totals = {"groups": 0, "messages": 0, "images": 0, "facts": 0, "label_queued": 0}
    label_quota = _LABEL_ENQUEUE_GLOBAL_PER_PASS
    bot_cache: dict[int, int] = {}
    for group_id in sorted(group_ids):
        try:
            cursor = cursors.get(group_id)
            if cursor is None:
                cursor = initial_cursor
            elif cursor[0] < now_ts - _CURSOR_STALE_SEC:
                # 久静默群恢复：游标过旧会引发追赶洪峰，直接跳回回填起点
                cursor = initial_cursor
            new_cursor, events, scanned = await _scan_group_messages(group_id=group_id, cursor=cursor, repo=repo)
            if scanned <= 0:
                continue
            totals["groups"] += 1
            totals["messages"] += scanned
            deltas = await _record_send_events(
                group_id=group_id, events=events, stat_repo=stat_repo, image_repo=image_repo
            )
            totals["images"] += sum(count for count, _last in deltas.values())
            # 游标先于投影落盘：投影失败靠下轮 candidates 自愈，统计不能重复计数
            cursors[group_id] = new_cursor
            _save_sticker_habit_cursors(cursors)
            facts, label_queued = await _project_group_habits(
                group_id=group_id,
                delta_pairs=set(deltas.keys()),
                stat_repo=stat_repo,
                cfg=cfg,
                bot_cache=bot_cache,
                label_quota=label_quota,
            )
            totals["facts"] += facts
            totals["label_queued"] += label_queued
            label_quota -= label_queued
        except Exception as exc:
            logger.warning("表情包习惯扫描群 [{}] 失败：{}", group_id, exc)
    await _prune_sticker_habit_stats(now_ts=now_ts, stat_repo=stat_repo)
    if totals["messages"] > 0:
        logger.info(
            "表情包习惯扫描完成：群 [{}]、消息 [{}]、图片 [{}]、事实 [{}]、补标 [{}]",
            totals["groups"],
            totals["messages"],
            totals["images"],
            totals["facts"],
            totals["label_queued"],
        )
    return totals


def _sticker_habit_prune_state_path() -> Path:
    return _sticker_habit_base_dir() / "prune_state.json"


def _should_run_sticker_habit_prune(now_ts: int) -> bool:
    """自然日闸：清理每天最多跑一次。"""
    try:
        raw = json.loads(_sticker_habit_prune_state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return True
    last_day = int(raw.get("last_prune_day") or 0) if isinstance(raw, dict) else 0
    return last_day != now_ts // 86400


def _mark_sticker_habit_prune_done(now_ts: int) -> None:
    atomic_write_text(
        _sticker_habit_prune_state_path(),
        json.dumps({"last_prune_day": now_ts // 86400}, ensure_ascii=False) + "\n",
    )


async def _prune_sticker_habit_stats(*, now_ts: int, stat_repo) -> int:
    """每天清理一次冷数据：只发过一两次、且长期未再发送的统计行。"""
    if not _should_run_sticker_habit_prune(now_ts):
        return 0
    try:
        deleted = await stat_repo.delete_cold(before_ts=now_ts - _PRUNE_AFTER_DAYS * 86400, max_count=_PRUNE_MAX_COUNT)
        _mark_sticker_habit_prune_done(now_ts)
        if deleted > 0:
            logger.info("表情包习惯统计清理完成，移除 [{}] 条冷数据", deleted)
        return int(deleted)
    except Exception as exc:
        logger.warning("表情包习惯统计清理失败：{}", exc)
        return 0


def bind_sticker_habit_lifecycle() -> None:
    """绑定表情包习惯扫描的生命周期（仅 bot 进程，30 分钟一轮）。"""
    global _STICKER_HABIT_LIFECYCLE_BOUND
    if _STICKER_HABIT_LIFECYCLE_BOUND:
        return
    _STICKER_HABIT_LIFECYCLE_BOUND = True
    driver = get_driver()

    @driver.on_startup
    async def _start_sticker_habit_worker() -> None:
        register_startup_scheduled("表情包习惯扫描")

        async def _run() -> None:
            while True:
                try:
                    from pallas.core.platform.ingress.message_load import is_overloaded

                    if not is_overloaded():
                        await run_sticker_habit_pass()
                except Exception as exc:
                    logger.warning("表情包习惯扫描循环失败：{}", exc)
                await asyncio.sleep(STICKER_HABIT_SCAN_INTERVAL_SEC)

        task = asyncio.create_task(_run(), name="sticker_habit_worker")
        driver._pallas_sticker_habit_task = task

    @driver.on_shutdown
    async def _stop_sticker_habit_worker() -> None:
        task = getattr(driver, "_pallas_sticker_habit_task", None)
        if task is None:
            return
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        driver._pallas_sticker_habit_task = None
