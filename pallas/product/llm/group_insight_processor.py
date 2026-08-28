"""群洞察处理器：从已入库 message 表派生 LLM 参数。

对外只暴露一个 work handler ``handle_group_insight``，内部按 ``payload["task"]``
分发到多个子处理函数，避免消费端过多导致开发散乱。relation/人物事实维持其
事件驱动独立链路，不进本处理器。
"""

from __future__ import annotations

import asyncio
import re
import time
from bisect import bisect_left
from operator import itemgetter
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
_SWEEP_BATCH_SIZE = 24
_PAIR_PAGE_LIMIT = 12
_SWEEP_STARTUP_POLL_SEC = 30
# 增量处理窗口：游标之后的新消息回溯上限。上一轮已处理到的消息时间记为游标，
# 本窗口内新消息才送 LLM 标注，避免长时段静默群每轮把历史窗口整体重扫。
_SEMANTIC_WINDOW_SEC = 2 * 60 * 60

# 群表达指导只看「前句→接话」的回复关系，不关心媒体细节：把 CQ 媒体码替换成
# 通用占位符（图 → [图片]、表情 → [表情]、其它 → [媒体]），避免 LLM 读到不可读的原始码。
_CQ_SEGMENT_RE = re.compile(r"\[CQ:([a-z]+)[^\]]*\]", re.IGNORECASE)
_CQ_PLACEHOLDER_MAP = {
    "image": "[图片]",
    "mface": "[图片]",
    "record": "[图片]",
    "face": "[表情]",
}


def _cq_placeholder(match: re.Match[str]) -> str:
    return _CQ_PLACEHOLDER_MAP.get(match.group(1).lower(), "[媒体]")


# 群级「语义采集 bot 指定」配置键：群维度指定一个稳定账号承担该群语义学习，
# 避免多 bot 并发群里任一台离线就停更。未指定时回退到「该群有处理记录的本地 bot 中最小者」。
_SEMANTIC_BOT_KEY = "semantic_style_bot_id"
_SEMANTIC_BOT_PLUGIN = "repeater"
_SEMANTIC_LOOKBACK_DAYS = 7

_GROUP_INSIGHT_LIFECYCLE_BOUND = False

# 候选群列表轮转游标：记录上次 `_sweep_semantic_groups` 处理到的偏移，
# 下一轮从该位置继续，遇列表末尾回绕，保证所有候选群在多轮内都被覆盖，
# 避免排序后固定取头部导致部分群（如多 bot 并发测试群）长期饿死。
_sweep_cursor = 0


async def handle_group_insight(payload: dict[str, Any]) -> None:
    """按 ``task`` 分发群洞察子任务。所有分支均返回 None（work aux handler 契约）。"""
    task = str(payload.get("task") or "")
    if task == "semantic":
        await _produce_semantic_profile(payload)
    elif task == "style_profile":
        await _compute_group_style_profile(payload)
    else:
        logger.warning("群洞察忽略未知任务 [{}]", task)


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
        get_semantic_style_group_cursor,
        is_human_semantic_style_pair,
        label_semantic_style_batch_with_llm,
        labeled_semantic_style_reply_ids,
        mark_semantic_style_group_processed,
        persist_semantic_style_examples,
        semantic_style_collection_enabled,
    )

    if not semantic_style_collection_enabled(bot_id=bot_id, group_id=group_id):
        return

    from pallas.product.llm.repeater_semantic_style import semantic_label_budget_ok

    if not semantic_label_budget_ok():
        logger.info("今日语义标注已达上限，跳过本群 [{}]", group_id)
        return

    pairs = await _rebuild_pairs_from_messages(bot_id=bot_id, group_id=group_id)
    if not pairs:
        return

    # 跳过已落库样本的接话、已处理过的旧窗口，避免同一批消息反复送 LLM 标注。
    now_ts = int(time.time())
    labeled_ids = labeled_semantic_style_reply_ids(bot_id=bot_id, group_id=group_id)
    cursor = get_semantic_style_group_cursor(bot_id=bot_id, group_id=group_id)
    pairs = [
        pair
        for pair in pairs
        if pair[5] not in labeled_ids and (cursor <= 0 or pair[6] > cursor) and pair[6] >= now_ts - _SEMANTIC_WINDOW_SEC
    ]
    if not pairs:
        return

    # 一次 LLM 提交标注多个候选对，降低调用成本。
    labeled = await label_semantic_style_batch_with_llm([
        (trigger, reply, pair_relation) for trigger, reply, pair_relation, *_ in pairs
    ])
    if len(labeled) != len(pairs):
        return

    accepted: list[SemanticStyleExample] = []
    accepted_ids: set[str] = set()
    max_processed_ts = 0
    for (trigger, reply, pair_relation, trigger_user_id, reply_user_id, message_id, created_at, is_bot_reply), (
        label,
        strategy,
    ) in zip(pairs, labeled, strict=True):
        max_processed_ts = max(max_processed_ts, int(created_at))
        if not label.is_reply_pair or not label.transferable:
            continue
        if not is_bot_reply and not is_human_semantic_style_pair(
            trigger_user_id=trigger_user_id,
            reply_user_id=reply_user_id,
            bot_id=bot_id,
        ):
            continue
        example_id = f"{group_id}:{message_id}:{bot_id}"
        if example_id in accepted_ids:
            continue
        accepted_ids.add(example_id)
        accepted.append(
            SemanticStyleExample(
                example_id=example_id,
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
                bot_style_positive=is_bot_reply,
            )
        )
    if accepted:
        persist_semantic_style_examples(accepted)
        logger.info(
            "群洞察已产出 [{}] 条语义样本，群 [{}]、账号 [{}]",
            len(accepted),
            group_id,
            bot_id,
        )
    mark_semantic_style_group_processed(bot_id=bot_id, group_id=group_id, processed_at=max_processed_ts)


async def _rebuild_pairs_from_messages(
    *, bot_id: int, group_id: int, limit: int = _MAX_PAIRS_PER_JOB
) -> list[tuple[str, str, str, int, int, int, int, bool]]:
    """从 message 表重建「前句→接话」对，返回 (trigger, reply, relation, t_uid, r_uid, mid, created_at, is_bot_reply)。

    多 bot 并发旁路记录会让同一条真人消息以不同 ``bot_id`` 落多行（message_id 相同），
    若只取最近一窗口会被 bot 重复记录塞满。这里按 message_id 去重（保留任意一条，
    因为同 message_id 的 user_id/正文/时间一致），并分页回溯避免窗口过窄。

    ``is_bot_reply`` 标记接话端是否为 bot（自身或协作 bot）：真人接话进入 direct_pairs，
    bot 自我接话只沉淀 behavior_strategy（self_reflection），不污染群表达指导。
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
        # 用批内最小 time 作为下一批边界；同秒多条消息时会因 time < before_time
        # 严格小于而被跳过（可接受：此类刷屏群窗口去重后仍能覆盖主体，改为复合游标
        # 需扩展 find_recent_in_group，收益低）。
        before_time = earliest

    ordered = sorted(unique_map.values(), key=lambda item: int(getattr(item, "time", 0) or 0))
    if not ordered:
        return []

    by_message_id = {int(getattr(item, "message_id", 0) or 0): item for item in ordered}
    # 真人序列：剔除 bot/状态消息后保留真人前后顺序，用于「跳过 bot 找相邻接话」。
    # adjacent 对的 trigger 端取 reply 之前最近的一条真人消息；reply 端可为真人(接入 direct_pairs)
    # 或 bot(settle self_reflection)，两者都从真人序列里取 trigger。
    human_ordered = [
        item
        for item in ordered
        if item is not None
        and sender_kind(int(getattr(item, "user_id", 0) or 0), self_bot_id=bot_id) == "human"
        and _text(getattr(item, "plain_text", "") or getattr(item, "raw_message", ""))
    ]
    human_times = [int(getattr(item, "time", 0) or 0) for item in human_ordered]
    pairs: list[tuple[str, str, str, int, int, int, int, bool]] = []
    seen: set[tuple[int, int]] = set()

    for reply_message in ordered:
        reply_user_id = int(getattr(reply_message, "user_id", 0) or 0)
        reply_text = _text(getattr(reply_message, "plain_text", "") or getattr(reply_message, "raw_message", ""))
        if not reply_text:
            continue
        reply_is_bot = sender_kind(reply_user_id, self_bot_id=bot_id) != "human"
        reply_id = int(getattr(reply_message, "message_id", 0) or 0)
        if reply_id <= 0:
            continue
        reply_time = int(getattr(reply_message, "time", 0) or 0)
        replied_message_id = int(getattr(reply_message, "reply_to_message_id", 0) or 0)
        # 1) 引用对：reply 显式引用了一条已知真人消息。
        if replied_message_id > 0:
            trigger = by_message_id.get(replied_message_id)
            if trigger is not None:
                trigger_user_id = int(getattr(trigger, "user_id", 0) or 0)
                trigger_text = _text(getattr(trigger, "plain_text", "") or getattr(trigger, "raw_message", ""))
                if (
                    trigger_text
                    and sender_kind(trigger_user_id, self_bot_id=bot_id) == "human"
                    and (replied_message_id, reply_id) not in seen
                ):
                    seen.add((replied_message_id, reply_id))
                    pairs.append((
                        trigger_text,
                        reply_text,
                        "quoted",
                        trigger_user_id,
                        reply_user_id,
                        reply_id,
                        reply_time,
                        reply_is_bot,
                    ))
                    continue
        # 2) 相邻对：取 reply 之前「最近的一条真人消息」作 trigger，跳过中间 bot/状态消息。
        pos = bisect_left(human_times, reply_time)
        if pos == 0:
            continue
        predecessor = human_ordered[pos - 1]
        predecessor_id = int(getattr(predecessor, "message_id", 0) or 0)
        if predecessor_id == reply_id or (predecessor_id, reply_id) in seen:
            continue
        trigger_text = _text(getattr(predecessor, "plain_text", "") or getattr(predecessor, "raw_message", ""))
        if not trigger_text or trigger_text == reply_text:
            continue
        seen.add((predecessor_id, reply_id))
        pairs.append((
            trigger_text,
            reply_text,
            "adjacent",
            int(getattr(predecessor, "user_id", 0) or 0),
            reply_user_id,
            reply_id,
            reply_time,
            reply_is_bot,
        ))
        if len(pairs) >= limit:
            break
    return pairs


def _text(value: object) -> str:
    """清洗文本：折叠空白并截断，同时把 CQ 媒体码替换成占位符。

    群表达指导只关心「前句→接话」的回复关系，不需要图片细节；用占位符让
    LLM 理解此处有媒体（图/表情），而非暴露不可读的原始 CQ 码。
    """
    raw = str(value or "")
    raw = _CQ_SEGMENT_RE.sub(_cq_placeholder, raw)
    return " ".join(raw.strip().split())[:240]


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

    候选群按「需要程度」排序：无语义 profile 或 sample_count 最少的群优先入队，
    避免固定取候选列表头部导致部分长期未采样的活跃群（如多 bot 并发测试群）被饿死。
    """
    store = build_work_job_store()
    repo = make_message_repository()
    now_ts = int(time.time())
    day = _day_key(now_ts)
    cutoff = now_ts - _SEMANTIC_LOOKBACK_DAYS * 24 * 60 * 60

    from pallas.product.llm.repeater_semantic_style import cached_semantic_style_profile

    seen_groups: set[int] = set()
    _local = await _local_bot_ids()
    for bot_id in _local:
        try:
            group_ids = await repo.list_recent_group_ids_for_bot(bot_id, since_time=cutoff, limit=128)
        except Exception as exc:
            logger.warning("群洞察扫描无法列出账号 [{}] 的活跃群：{}", bot_id, exc)
            continue
        seen_groups.update(group_ids)
    if not seen_groups:
        return

    pending: list[tuple[int, int, int]] = []
    for group_id in sorted(seen_groups):
        semantic_bot = await _resolve_semantic_bot(group_id)
        if semantic_bot <= 0:
            continue
        if not await _group_needs_semantic(bot_id=semantic_bot, group_id=group_id):
            continue
        profile = cached_semantic_style_profile(semantic_bot, group_id, _SCENE)
        sample_count = int(profile.sample_count) if profile is not None else 0
        pending.append((sample_count, semantic_bot, group_id))

    pending.sort(key=itemgetter(0, 2))
    if not pending:
        return

    global _sweep_cursor
    count = len(pending)
    start = _sweep_cursor % count
    # 从 start 开始跨越末尾续取 batch 个，保证轮转覆盖且不重复。
    selected = (pending[start:] + pending[:start])[:_SWEEP_BATCH_SIZE]
    _sweep_cursor = (start + len(selected)) % count

    for _sample_count, semantic_bot, group_id in selected:
        try:
            await store.enqueue(build_semantic_insight_job(bot_id=semantic_bot, group_id=group_id, day=day))
            logger.info("群洞察已入队语义任务，群 [{}]、帐号 [{}]", group_id, semantic_bot)
        except Exception as exc:
            logger.warning("群洞察扫描入队语义任务失败，群 [{}]：{}", group_id, exc)


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
        logger.warning("群洞察无法列出群 [{}] 的帐号：{}", group_id, exc)
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
            logger.info("群洞察扫描等待牛牛连接")
            await asyncio.sleep(_SWEEP_STARTUP_POLL_SEC)
            continue
        try:
            await _sweep_semantic_groups()
        except Exception as exc:
            logger.warning("群洞察语义扫描失败：{}", exc)
        await asyncio.sleep(_SWEEP_INTERVAL_SEC)


def register_group_insight_startup_hook() -> None:
    global _GROUP_INSIGHT_LIFECYCLE_BOUND
    if _GROUP_INSIGHT_LIFECYCLE_BOUND:
        return
    _GROUP_INSIGHT_LIFECYCLE_BOUND = True
    driver = get_driver()

    @driver.on_startup
    async def _start_group_insight_sweep() -> None:
        register_startup_scheduled("群洞察扫描")
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
