"""群洞察处理器：从已入库 message 表派生 LLM 参数。

对外只暴露一个 work handler ``handle_group_insight``，内部按 ``payload["task"]``
分发到多个子处理函数，避免消费端过多导致开发散乱。relation/人物事实维持其
事件驱动独立链路，不进本处理器。
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from nonebot import get_driver, logger

from pallas.core.foundation.db import make_message_repository
from pallas.core.foundation.startup_report import register_startup_scheduled
from pallas.core.platform.work_jobs.models import WorkJob
from pallas.core.platform.work_jobs.runtime import build_work_job_store
from pallas.product.llm.sender_identity import sender_kind

GROUP_INSIGHT_KIND = "group.insight"

_SCENE = "group_chat"
_MAX_PAIRS_PER_JOB = 40
_SWEEP_INTERVAL_SEC = 20 * 60
_SWEEP_BATCH_SIZE = 8
_PAIR_PAGE_LIMIT = 6
_SWEEP_STARTUP_POLL_SEC = 30

# 群级「语义采集 bot 指定」配置键：群维度指定一个稳定账号承担该群语义学习，
# 避免多 bot 并发群里任一台离线就停更。未指定时回退到「该群有处理记录的本地 bot 中最小者」。
_SEMANTIC_BOT_KEY = "semantic_style_bot_id"
_SEMANTIC_BOT_PLUGIN = "repeater"
_SEMANTIC_LOOKBACK_DAYS = 7

_GROUP_INSIGHT_LIFECYCLE_BOUND = False


async def handle_group_insight(payload: dict[str, Any]) -> None:
    """按 ``task`` 分发群洞察子任务。所有分支均返回 None（work aux handler 契约）。"""
    task = str(payload.get("task") or "")
    if task == "semantic":
        await _produce_semantic_profile(payload)
    elif task == "style_profile":
        await _compute_group_style_profile(payload)
    else:
        logger.warning("Group insight ignored unknown task [{}]", task)


async def _compute_group_style_profile(payload: dict[str, Any]) -> None:
    """确定性层：刷新单个群的回复形状 profile，写入 group_config.style_profile。"""
    group_id = int(payload.get("group_id") or 0)
    if group_id <= 0:
        return
    from pallas.product.persona.group_style_refresh import refresh_group_style_profile

    await refresh_group_style_profile(group_id)


async def _produce_semantic_profile(payload: dict[str, Any]) -> None:
    """语义层：重建成对样本并为单个群产出语义风格 profile 到 profiles.json。"""
    bot_id = int(payload.get("bot_id") or 0)
    group_id = int(payload.get("group_id") or 0)
    if bot_id <= 0 or group_id <= 0:
        return
    from pallas.product.llm.repeater_semantic_style import (
        SemanticStyleExample,
        is_human_semantic_style_pair,
        label_semantic_style_with_retry,
        persist_semantic_style_example,
        semantic_style_collection_enabled,
    )

    if not semantic_style_collection_enabled(bot_id=bot_id, group_id=group_id):
        return

    pairs = await _rebuild_pairs_from_messages(bot_id=bot_id, group_id=group_id)
    if not pairs:
        return

    persisted = 0
    for trigger, reply, pair_relation, trigger_user_id, reply_user_id, message_id, created_at in pairs:
        if not is_human_semantic_style_pair(
            trigger_user_id=trigger_user_id,
            reply_user_id=reply_user_id,
            bot_id=bot_id,
        ):
            continue
        label_result = await label_semantic_style_with_retry(
            trigger_text=trigger,
            reply_text=reply,
            pair_relation=pair_relation,
        )
        if label_result is None:
            continue
        label, strategy = label_result
        if not label.is_reply_pair or not label.transferable:
            continue
        example = SemanticStyleExample(
            example_id=f"{group_id}:{message_id}:{bot_id}",
            created_at=int(created_at),
            bot_id=bot_id,
            group_id=group_id,
            scene=_SCENE,
            trigger_text=trigger,
            reply_text=reply,
            label=label,
            source_kind="human_pair",
            trigger_user_id=int(trigger_user_id),
            reply_user_id=int(reply_user_id),
            pair_relation=pair_relation,
            annotation_source="llm_v2",
            behavior_strategy=strategy,
        )
        persist_semantic_style_example(example)
        persisted += 1
    if persisted:
        logger.info(
            "Group insight semantic produced [{}] examples for bot [{}] and group [{}]", persisted, bot_id, group_id
        )


async def _rebuild_pairs_from_messages(
    *, bot_id: int, group_id: int, limit: int = _MAX_PAIRS_PER_JOB
) -> list[tuple[str, str, str, int, int, int, int]]:
    """从 message 表重建成人「前句→接话」对，返回 (trigger, reply, relation, t_uid, r_uid, mid, created_at)。

    多 bot 并发旁路记录会让同一条真人消息以不同 ``bot_id`` 落多行（message_id 相同），
    若只取最近一窗口会被 bot 重复记录塞满。这里按 message_id 去重（保留任意一条，
    因为同 message_id 的 user_id/正文/时间一致），并分页回溯避免窗口过窄。
    """
    repo = make_message_repository()
    now_ts = int(time.time())
    before_time = now_ts + 1
    unique_map: dict[int, object] = {}
    for _ in range(_PAIR_PAGE_LIMIT):
        batch = await repo.find_recent_in_group(group_id, before_time=before_time, limit=32)
        if not batch:
            break
        earliest = None
        for item in batch:
            mid = int(getattr(item, "message_id", 0) or 0)
            if mid <= 0:
                continue
            unique_map.setdefault(mid, item)
            ts = int(getattr(item, "time", 0) or 0)
            if earliest is None or ts < earliest:
                earliest = ts
        if earliest is None or earliest >= before_time:
            break
        before_time = earliest

    ordered = sorted(unique_map.values(), key=lambda item: int(getattr(item, "time", 0) or 0))
    if not ordered:
        return []

    by_message_id = {int(getattr(item, "message_id", 0) or 0): item for item in ordered}
    pairs: list[tuple[str, str, str, int, int, int, int]] = []
    seen: set[tuple[int, int]] = set()

    for index, reply_message in enumerate(ordered):
        reply_user_id = int(getattr(reply_message, "user_id", 0) or 0)
        reply_text = _text(getattr(reply_message, "plain_text", "") or getattr(reply_message, "raw_message", ""))
        if not reply_text or sender_kind(reply_user_id, self_bot_id=bot_id) != "human":
            continue
        replied_message_id = int(getattr(reply_message, "reply_to_message_id", 0) or 0)
        if replied_message_id > 0:
            trigger = by_message_id.get(replied_message_id)
            if trigger is not None:
                trigger_user_id = int(getattr(trigger, "user_id", 0) or 0)
                trigger_text = _text(getattr(trigger, "plain_text", "") or getattr(trigger, "raw_message", ""))
                if (
                    trigger_text
                    and sender_kind(trigger_user_id, self_bot_id=bot_id) == "human"
                    and (replied_message_id, int(getattr(reply_message, "message_id", 0) or 0)) not in seen
                ):
                    seen.add((replied_message_id, int(getattr(reply_message, "message_id", 0) or 0)))
                    pairs.append((
                        trigger_text,
                        reply_text,
                        "quoted",
                        trigger_user_id,
                        reply_user_id,
                        int(getattr(reply_message, "message_id", 0) or 0),
                        int(getattr(reply_message, "time", 0) or 0),
                    ))
                    continue
        if index == 0:
            continue
        predecessor = ordered[index - 1]
        predecessor_user_id = int(getattr(predecessor, "user_id", 0) or 0)
        if sender_kind(predecessor_user_id, self_bot_id=bot_id) != "human":
            continue
        trigger_text = _text(getattr(predecessor, "plain_text", "") or getattr(predecessor, "raw_message", ""))
        if not trigger_text or trigger_text == reply_text:
            continue
        message_id = int(getattr(reply_message, "message_id", 0) or 0)
        predecessor_id = int(getattr(predecessor, "message_id", 0) or 0)
        if (predecessor_id, message_id) in seen:
            continue
        seen.add((predecessor_id, message_id))
        pairs.append((
            trigger_text,
            reply_text,
            "adjacent",
            predecessor_user_id,
            reply_user_id,
            message_id,
            int(getattr(reply_message, "time", 0) or 0),
        ))
        if len(pairs) >= limit:
            break
    return pairs


def _text(value: object) -> str:
    return " ".join(str(value or "").strip().split())[:240]


def build_semantic_insight_job(*, bot_id: int, group_id: int, day: int) -> WorkJob:
    return WorkJob.create(
        kind=GROUP_INSIGHT_KIND,
        payload={
            "task": "semantic",
            "bot_id": int(bot_id),
            "group_id": int(group_id),
        },
        idempotency_key=f"group.insight:semantic:{int(bot_id)}:{int(group_id)}:{int(day)}",
    )


async def _sweep_semantic_groups() -> None:
    """低频扫描当天有新消息、尚未积累语义样本的群，入队 group.insight semantic job。

    不再依赖「特定 bot 在线」：枚举所有本机 bot 近期有处理记录的群并集，每个群
    单独解析出语义采集 bot（见 ``_resolve_semantic_bot``），避免多 bot 并发群里
    主 bot 离线导致画像停更。
    """
    store = build_work_job_store()
    repo = make_message_repository()
    now_ts = int(time.time())
    day = _day_key(now_ts)
    cutoff = now_ts - _SEMANTIC_LOOKBACK_DAYS * 24 * 60 * 60
    seen_groups: set[int] = set()
    enqueued = 0
    _local = await _local_bot_ids()
    for bot_id in _local:
        try:
            group_ids = await repo.list_recent_group_ids_for_bot(bot_id, since_time=cutoff, limit=128)
        except Exception as exc:
            logger.warning("Group insight sweep could not list groups for bot [{}]: [{}]", bot_id, exc)
            continue
        for group_id in group_ids:
            if group_id in seen_groups:
                continue
            seen_groups.add(group_id)
            semantic_bot = await _resolve_semantic_bot(group_id)
            if semantic_bot <= 0:
                continue
            if not await _group_needs_semantic(bot_id=semantic_bot, group_id=group_id):
                continue
            await store.enqueue(build_semantic_insight_job(bot_id=semantic_bot, group_id=group_id, day=day))
            enqueued += 1
            if enqueued >= _SWEEP_BATCH_SIZE:
                return
        if enqueued >= _SWEEP_BATCH_SIZE:
            return


async def _resolve_semantic_bot(group_id: int) -> int:
    """解析某群承担语义学习、作为 profile 归属账号的 bot_id。

    优先读群级配置指定的账号；未指定则回退到「该群最近有处理记录的本地部署 bot 中
    bot_id 最小者」，保证多 bot 并发群里任一账号离线也能确定一个稳定归属。
    """
    if group_id <= 0:
        return 0
    from pallas.core.platform.multi_bot.fleet import get_catalog_bot_ids
    from pallas.core.storage.store import GroupPluginStorage

    try:
        configured = await GroupPluginStorage(_SEMANTIC_BOT_PLUGIN, group_id).get(_SEMANTIC_BOT_KEY)
        configured = int(configured) if configured else 0
    except Exception:
        configured = 0
    if configured > 0:
        return configured

    repo = make_message_repository()
    now_ts = int(time.time())
    cutoff = now_ts - _SEMANTIC_LOOKBACK_DAYS * 24 * 60 * 60
    try:
        bot_ids = await repo.list_recent_bot_ids_for_group(group_id, since_time=cutoff, limit=128)
    except Exception as exc:
        logger.warning("Group insight could not list bots for group [{}]: [{}]", group_id, exc)
        return 0
    catalog = get_catalog_bot_ids()
    local = sorted(int(b) for b in bot_ids if int(b) in catalog)
    return local[0] if local else 0


async def _group_needs_semantic(*, bot_id: int, group_id: int) -> bool:
    from pallas.product.llm.repeater_semantic_style import (
        cached_semantic_style_profile,
        semantic_style_collection_enabled,
    )

    if not semantic_style_collection_enabled(bot_id=bot_id, group_id=group_id):
        return False
    profile = cached_semantic_style_profile(bot_id, group_id, _SCENE)
    if profile is None:
        return True
    return int(profile.sample_count) < 10


async def _local_bot_ids() -> set[int]:
    from nonebot import get_bots

    ids = set()
    for _key, bot in get_bots().items():
        try:
            ids.add(int(getattr(bot, "self_id", _key)))
        except (TypeError, ValueError):
            continue
    return ids


def _day_key(ts: int) -> int:
    return int(ts // 86400)


async def _sweep_loop() -> None:
    while True:
        _local = await _local_bot_ids()
        if not _local:
            logger.info("Group insight sweep waiting for bots to connect")
            await asyncio.sleep(_SWEEP_STARTUP_POLL_SEC)
            continue
        try:
            await _sweep_semantic_groups()
        except Exception as exc:
            logger.warning("Group insight semantic sweep failed: {}", exc)
        await asyncio.sleep(_SWEEP_INTERVAL_SEC)


def register_group_insight_startup_hook() -> None:
    global _GROUP_INSIGHT_LIFECYCLE_BOUND
    if _GROUP_INSIGHT_LIFECYCLE_BOUND:
        return
    _GROUP_INSIGHT_LIFECYCLE_BOUND = True
    driver = get_driver()

    @driver.on_startup
    async def _start_group_insight_sweep() -> None:
        register_startup_scheduled("group.insight sweep")
        task = asyncio.create_task(_sweep_loop(), name="group_insight_sweep_worker")
        driver._pallas_group_insight_sweep_task = task

    @driver.on_shutdown
    async def _stop_group_insight_sweep() -> None:
        task = getattr(driver, "_pallas_group_insight_sweep_task", None)
        if task is None:
            return
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        driver._pallas_group_insight_sweep_task = None
