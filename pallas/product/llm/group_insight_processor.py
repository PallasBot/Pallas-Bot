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

GROUP_INSIGHT_KIND = "group.insight"

_SCENE = "group_chat"
_MAX_PAIRS_PER_JOB = 24
_SWEEP_INTERVAL_SEC = 6 * 60 * 60
_SWEEP_BATCH_SIZE = 1024
_PAIR_PAGE_LIMIT = 96
_SWEEP_STARTUP_POLL_SEC = 30

# 群表达指导只看「前句→接话」的回复关系，不关心媒体细节：把 CQ 媒体码替换成
# 通用占位符（图 → [图片]、表情 → [表情]、其它 → [媒体]），避免 LLM 读到不可读的原始码。
_CQ_SEGMENT_RE = re.compile(r"\[CQ:([a-z]+)[^\]]*\]", re.IGNORECASE)
_CQ_PLACEHOLDER_MAP = {
    "image": "[图片]",
    "mface": "[图片]",
    "record": "[图片]",
    "face": "[表情]",
}

# 接话端只剩图片/媒体占位（无任何文字）时对 LLM 标注没有信息量，直接跳过；
# [表情] 是真实的文字化接话，不在此列。
_MEDIA_ONLY_REPLY_RE = re.compile(r"(?:\s*(?:\[图片\]|\[媒体\])\s*)+")
_PUNCTUATION_ONLY_REPLY_RE = re.compile(r"[!-/:-@[-`{-~。！？、；：…]+")


def _cq_placeholder(match: re.Match[str]) -> str:
    return _CQ_PLACEHOLDER_MAP.get(match.group(1).lower(), "[媒体]")


# 群级「语义采集 bot 指定」配置键：群维度指定一个稳定账号承担该群语义学习，
# 避免多 bot 并发群里任一台离线就停更。未指定时回退到「该群有处理记录的本地 bot 中最小者」。
_SEMANTIC_BOT_KEY = "semantic_style_bot_id"
_SEMANTIC_BOT_PLUGIN = "repeater"
_SEMANTIC_LOOKBACK_DAYS = 7

_GROUP_INSIGHT_LIFECYCLE_BOUND = False

# 候选群列表轮转游标：保留上限以防群数量异常增长，正常部署可在一个六小时周期
# 内覆盖当前全部活跃群；超过上限时下一轮从上次位置继续，避免固定取头部饿死。
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

    cursor_time, cursor_message_id = get_semantic_style_group_cursor(bot_id=bot_id, group_id=group_id)
    known_bots = await _known_bots_in_group(group_id)
    pairs = await _rebuild_pairs_from_messages(
        bot_id=bot_id,
        group_id=group_id,
        after_time=cursor_time,
        after_message_id=cursor_message_id,
        known_bots=known_bots,
    )
    if not pairs:
        return

    # 跳过已落库样本的接话、已处理过的旧窗口，避免同一批消息反复送 LLM 标注。
    labeled_ids = labeled_semantic_style_reply_ids(bot_id=bot_id, group_id=group_id)
    pairs = [pair for pair in pairs if pair[5] not in labeled_ids]
    if not pairs:
        return

    # 一次 LLM 提交标注多个候选对，降低调用成本；预算中途耗尽时返回长度
    # 可能短于 pairs，按前缀对齐只处理已尝试部分。
    labeled = await label_semantic_style_batch_with_llm([
        (trigger, reply, pair_relation) for trigger, reply, pair_relation, *_ in pairs
    ])
    if not labeled or len(labeled) > len(pairs):
        return
    if all(item is None for item in labeled):
        return
    attempted = pairs[: len(labeled)]

    accepted: list[SemanticStyleExample] = []
    accepted_ids: set[str] = set()
    max_processed_key = (0, 0)
    for (
        trigger,
        reply,
        pair_relation,
        trigger_user_id,
        reply_user_id,
        message_id,
        created_at,
        is_bot_reply,
    ), labeled_item in zip(attempted, labeled, strict=True):
        # 失败对也计入游标推进：单对回退路径已内置重试，滞留旧窗只会让
        # 下一轮 sweep 对同一窗口原样重发；全部失败时才保留游标待下轮。
        max_processed_key = max(max_processed_key, (int(created_at), int(message_id)))
        if labeled_item is None:
            continue
        label, strategy = labeled_item
        if not label.is_reply_pair or not label.transferable:
            continue
        if not is_bot_reply and not is_human_semantic_style_pair(
            trigger_user_id=trigger_user_id,
            reply_user_id=reply_user_id,
            bot_id=bot_id,
            known_bots=known_bots,
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
                reply_is_bot=is_bot_reply,
            )
        )
    if accepted:
        persist_semantic_style_examples(accepted)
        logger.debug(
            "群洞察已产出 [{}] 条语义样本，群 [{}]、账号 [{}]",
            len(accepted),
            group_id,
            bot_id,
        )
    mark_semantic_style_group_processed(
        bot_id=bot_id,
        group_id=group_id,
        processed_at=max_processed_key[0],
        processed_message_id=max_processed_key[1],
    )


def _is_bot_sender(*, user_id: int, self_bot_id: int, known_bots: set[int]) -> bool:
    """接话端是否为 bot（自身或已知协作 bot）。

    work aux 进程不连接 QQ，``sender_kind`` 的 peer 判定（connected roster /
    federate）不可靠，会把手动部署的协作 bot 误判为真人；以 message 表推导的
    ``known_bots`` 为准，``is_peer_bot`` 仅作兜底。
    """
    if user_id == self_bot_id:
        return True
    if user_id in known_bots:
        return True
    from pallas.product.llm.sender_identity import is_peer_bot

    return is_peer_bot(user_id)


async def _known_bots_in_group(group_id: int) -> set[int]:
    """该群近期作为 bot 记录过消息的账号集合（含本机与协作 bot）。

    message 表的 ``bot_id`` 是记录者账号：任何在该群以 bot_id 出现过的账号，
    其 user_id 发言都应视为 bot 消息，而不是真人接话参考。
    """
    repo = make_message_repository()
    now_ts = int(time.time())
    cutoff = now_ts - _SEMANTIC_LOOKBACK_DAYS * 24 * 60 * 60
    try:
        bot_ids = await repo.list_recent_bot_ids_for_group(group_id, since_time=cutoff, limit=128)
    except Exception as exc:
        logger.warning("群洞察无法列出群 [{}] 的已知账号：{}", group_id, exc)
        return set()
    return {int(b) for b in bot_ids if int(b) > 0}


async def _rebuild_pairs_from_messages(
    *,
    bot_id: int,
    group_id: int,
    limit: int = _MAX_PAIRS_PER_JOB,
    after_time: int = 0,
    after_message_id: int | None = None,
    known_bots: set[int] | None = None,
) -> list[tuple[str, str, str, int, int, int, int, bool]]:
    """从 message 表重建「前句→接话」对，返回 (trigger, reply, relation, t_uid, r_uid, mid, created_at, is_bot_reply)。

    多 bot 并发旁路记录会让同一条真人消息以不同 ``bot_id`` 落多行（message_id 相同），
    若只取最近一窗口会被 bot 重复记录塞满。这里按 message_id 去重（保留任意一条，
    因为同 message_id 的 user_id/正文/时间一致），并分页回溯避免窗口过窄。

    分页与 ``after_time``/``after_message_id`` 边界都按 ``(time, message_id)`` 复合
    比较，同秒内消息不会被秒级游标跳过；仅传 ``after_time`` 时视为整秒已处理。

    ``is_bot_reply`` 标记接话端是否为 bot（自身或协作 bot）：真人接话进入 direct_pairs，
    bot 自我接话只沉淀 behavior_strategy（self_reflection），不污染群表达指导。
    work aux 进程不连接 QQ，``sender_kind`` 的 peer 判定不可靠，因此以 message 表
    推导的 ``known_bots`` 为准。
    """
    repo = make_message_repository()
    known_bots = known_bots or set()
    now_ts = int(time.time())
    before_time = now_ts + 1
    before_message_id: int | None = None
    if after_time > 0:
        from pallas.product.llm.repeater_semantic_style import _CURSOR_MID_SENTINEL

        after_key = (int(after_time), _CURSOR_MID_SENTINEL if after_message_id is None else int(after_message_id))
    else:
        after_key = None
    unique_map: dict[int, object] = {}
    for _ in range(_PAIR_PAGE_LIMIT):
        batch = await repo.find_recent_in_group(
            group_id, before_time=before_time, before_message_id=before_message_id, limit=32
        )
        if not batch:
            break
        earliest_key: tuple[int, int] | None = None
        for item in batch:
            mid = int(getattr(item, "message_id", 0) or 0)
            if mid <= 0:
                continue
            unique_map.setdefault(mid, item)
            key = (int(getattr(item, "time", 0) or 0), mid)
            if earliest_key is None or key < earliest_key:
                earliest_key = key
        if earliest_key is None:
            break
        if after_key is not None and earliest_key <= after_key:
            break
        # 用批内最小 (time, message_id) 作为下一批复合边界，同秒剩余消息由
        # find_recent_in_group 的复合条件继续取出，不会因 time 相等被跳过。
        before_time, before_message_id = earliest_key

    ordered = sorted(
        unique_map.values(),
        key=lambda item: (int(getattr(item, "time", 0) or 0), int(getattr(item, "message_id", 0) or 0)),
    )
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
        and not _is_bot_sender(
            user_id=int(getattr(item, "user_id", 0) or 0),
            self_bot_id=bot_id,
            known_bots=known_bots,
        )
        and _text(getattr(item, "plain_text", "") or getattr(item, "raw_message", ""))
    ]
    human_keys = [
        (int(getattr(item, "time", 0) or 0), int(getattr(item, "message_id", 0) or 0)) for item in human_ordered
    ]
    pairs: list[tuple[str, str, str, int, int, int, int, bool]] = []
    adjacent_pairs: list[tuple[str, str, str, int, int, int, int, bool]] = []
    seen: set[tuple[int, int]] = set()

    for reply_message in ordered:
        reply_user_id = int(getattr(reply_message, "user_id", 0) or 0)
        reply_text = _text(getattr(reply_message, "plain_text", "") or getattr(reply_message, "raw_message", ""))
        if not reply_text or _MEDIA_ONLY_REPLY_RE.fullmatch(reply_text):
            continue
        reply_is_bot = _is_bot_sender(user_id=reply_user_id, self_bot_id=bot_id, known_bots=known_bots)
        reply_id = int(getattr(reply_message, "message_id", 0) or 0)
        if reply_id <= 0:
            continue
        reply_time = int(getattr(reply_message, "time", 0) or 0)
        if after_key is not None and (reply_time, reply_id) <= after_key:
            continue
        replied_message_id = int(getattr(reply_message, "reply_to_message_id", 0) or 0)
        # 1) 引用对：reply 显式引用了一条已知真人消息。
        if replied_message_id > 0:
            trigger = by_message_id.get(replied_message_id)
            if trigger is not None:
                trigger_user_id = int(getattr(trigger, "user_id", 0) or 0)
                trigger_text = _text(getattr(trigger, "plain_text", "") or getattr(trigger, "raw_message", ""))
                if (
                    trigger_text
                    and not _is_bot_sender(user_id=trigger_user_id, self_bot_id=bot_id, known_bots=known_bots)
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
        if not reply_is_bot and _PUNCTUATION_ONLY_REPLY_RE.fullmatch(reply_text):
            continue
        # 2) 相邻对：取 reply 之前「最近的一条真人消息」作 trigger，跳过中间 bot/状态消息。
        pos = bisect_left(human_keys, (reply_time, reply_id))
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
        adjacent_pairs.append((
            trigger_text,
            reply_text,
            "adjacent",
            int(getattr(predecessor, "user_id", 0) or 0),
            reply_user_id,
            reply_id,
            reply_time,
            reply_is_bot,
        ))
    # 历史 LLM 标注中 quoted 样本几乎全部可接受，adjacent 命中率明显更低；
    # 先扫完整个窗口再拼接，quoted 排前，避免被大量低命中的 adjacent 挤出 limit。
    # adjacent 二级排序（均零 LLM，纯本地计算）：
    #   ① repeater answer 热度（真人反复接成功的对，见 _repeater_answer_heat）
    #   ② trigger/reply 文本相似度（无热度时按语义相关性兜底）
    #   ③ 原时间顺序保持稳定。
    heat = await _repeater_answer_heat(bot_id=bot_id, group_id=group_id) if bot_id > 0 else {}
    from pallas.product.llm.repeater_semantic_style import (
        normalize_semantic_style_match_text,
        semantic_style_text_similarity,
    )

    def _adjacent_rank(pair: tuple[str, str, str, int, int, int, int, bool]) -> tuple[int, float]:
        trigger, reply = pair[0], pair[1]
        heat_value = heat.get(
            (normalize_semantic_style_match_text(trigger), normalize_semantic_style_match_text(reply)),
            0,
        )
        return heat_value, semantic_style_text_similarity(trigger, reply)

    ranked_adjacent = [(_adjacent_rank(pair), pair) for pair in adjacent_pairs]
    ranked_adjacent.sort(key=lambda item: (-item[0][0], -item[0][1]))
    pairs.extend(pair for _, pair in ranked_adjacent)
    return pairs[:limit]


# 复读（repeater）语料近期窗口：只看近期接得成功的对，避免无限放大历史热度。
_REPEATER_HEAT_LOOKBACK_DAYS = 14


async def _repeater_answer_heat(*, bot_id: int, group_id: int) -> dict[tuple[str, str], int]:
    """从 repeater 语料（context answer）表聚合「真人触发→真人接话」热度。

    repeater learn 是零 LLM 的录音带：`Answer.count` 表示同一 trigger 下这条回复
    被真人反复接成功的次数（消费端还有 count/_topical 打分）。这里直接读库，把
    「真人反复接过的对」作为语义标注优先级依据——反复接得上的对才值得花 LLM
    提炼策略；零热度对仍按文本相似度排序兜底。
    """
    from pallas.core.foundation.db import make_local_context_repository
    from pallas.product.llm.repeater_semantic_style import normalize_semantic_style_match_text

    # 只读本地复读语料：Composite 包装面向接话热路径，未转发表级查询；
    # 语义采集本来就只关心本机 peered 群里的真人接话。
    repo = make_local_context_repository()
    cutoff = int(time.time()) - _REPEATER_HEAT_LOOKBACK_DAYS * 24 * 60 * 60
    try:
        answers = await repo.list_answers_for_group_since(group_id, cutoff)
    except Exception as exc:
        logger.warning("群洞察无法读取群 [{}] 的复读语料热度：{}", group_id, exc)
        return {}

    heat: dict[tuple[str, str], int] = {}
    for answer in answers:
        trigger = normalize_semantic_style_match_text(str(getattr(answer, "keywords", "") or ""))
        if not trigger:
            continue
        count = max(0, int(getattr(answer, "count", 0) or 0))
        for message in getattr(answer, "messages", []) or []:
            reply = normalize_semantic_style_match_text(str(message or ""))
            if not reply:
                continue
            key = (trigger, reply)
            heat[key] = max(heat.get(key, 0), count)
    return heat


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

    候选群按群号稳定排序并配合游标轮转，避免固定取候选列表头部导致部分活跃群
    长期未采样。是否实际调用 LLM 由 work 侧的持久化消息游标决定。
    """
    store = build_work_job_store()
    repo = make_message_repository()
    now_ts = int(time.time())
    day = _sweep_slot(now_ts)
    cutoff = now_ts - _SEMANTIC_LOOKBACK_DAYS * 24 * 60 * 60

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
        pending.append((0, semantic_bot, group_id))

    pending.sort(key=itemgetter(0, 2))
    if not pending:
        return

    global _sweep_cursor
    count = len(pending)
    start = _sweep_cursor % count
    # 从 start 开始跨越末尾续取 batch 个，保证轮转覆盖且不重复。
    selected = (pending[start:] + pending[:start])[:_SWEEP_BATCH_SIZE]
    _sweep_cursor = (start + len(selected)) % count

    enqueued = 0
    for _sample_count, semantic_bot, group_id in selected:
        try:
            await store.enqueue(build_semantic_insight_job(bot_id=semantic_bot, group_id=group_id, day=day))
            enqueued += 1
        except Exception as exc:
            logger.warning("群洞察扫描入队语义任务失败，群 [{}]：{}", group_id, exc)
    if enqueued:
        logger.info("群洞察扫描已入队 [{}] 个语义任务", enqueued)


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
        semantic_style_collection_enabled,
    )

    if not semantic_style_collection_enabled(bot_id=bot_id, group_id=group_id):
        return False
    return True


async def _local_bot_ids() -> set[int]:
    from nonebot import get_bots

    ids = set()
    for _key, bot in get_bots().items():
        try:
            ids.add(int(getattr(bot, "self_id", _key)))
        except (TypeError, ValueError):
            continue
    return ids


def _sweep_slot(ts: int) -> int:
    return int(ts // _SWEEP_INTERVAL_SEC)


def _sweep_wake_delay(now_ts: int) -> int:
    """距下一个 6h slot 边界的秒数。

    UTC 日边界是 slot 边界（86400 % 21600 == 0），因此按 slot 对齐醒来即覆盖
    预算窗口翻转（本地 08:00），避免「旧窗口跑满预算后新窗口要等一整轮 6h」的空转。
    """
    return _SWEEP_INTERVAL_SEC - (now_ts % _SWEEP_INTERVAL_SEC)


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
        await asyncio.sleep(_sweep_wake_delay(int(time.time())))


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
