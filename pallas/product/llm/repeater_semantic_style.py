"""后台标注复读语料，并向生成侧提供只读风格快照。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
import unicodedata
from collections import Counter, deque
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from typing import TYPE_CHECKING, Any, Literal

from nonebot import get_bots, get_driver, logger
from pydantic import BaseModel, ConfigDict, Field, model_validator

from pallas.core.foundation.db import make_local_context_repository, make_message_repository
from pallas.core.foundation.fs_lock import atomic_write_text, interprocess_file_lock
from pallas.core.foundation.logging import log_rate_limited
from pallas.core.foundation.paths import plugin_data_dir
from pallas.core.foundation.startup_report import register_startup_ready
from pallas.core.platform.work_jobs.models import WorkJob
from pallas.product.llm.inference_params import task_token_budget

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

SEMANTIC_STYLE_LABEL_VERSION = 2
SEMANTIC_STYLE_RETENTION_SEC = 90 * 24 * 60 * 60
BOT_STYLE_RECENT_SEC = 14 * 24 * 60 * 60
BOT_STYLE_POSITIVE_REPLY_SEC = 90
BOT_STYLE_PROMOTION_SAMPLE_COUNT = 20
BOT_STYLE_PROMOTION_RECENT_SAMPLE_COUNT = 8
SEMANTIC_STYLE_BACKFILL_WINDOW_SEC = 30 * 24 * 60 * 60
SEMANTIC_STYLE_BACKFILL_JOB_TTL_SEC = 7 * 24 * 60 * 60
SEMANTIC_STYLE_BACKFILL_MAX_PER_DAY = 128
SEMANTIC_STYLE_BACKFILL_ENABLED = True
SEMANTIC_STYLE_REALTIME_MAX_PER_DAY = 1000
SEMANTIC_STYLE_REALTIME_MAX_PER_SCOPE_PER_DAY = 40
SEMANTIC_STYLE_REALTIME_SAMPLE_DIVISOR = 2
SEMANTIC_STYLE_LABEL_MAX_RETRIES = 2
_BATCH_LABEL_MAX = 8
SEMANTIC_STYLE_LABEL_BATCH_MAX = _BATCH_LABEL_MAX
_SEMANTIC_STYLE_BACKFILL_GROUP_LIMIT = 128
_SEMANTIC_STYLE_BACKFILL_PAGE_SIZE = 32
_SEMANTIC_STYLE_BACKFILL_START_DELAY_SEC = 30.0
_SEMANTIC_STYLE_BACKFILL_INTERVAL_SEC = 24 * 60 * 60

_INTENSITY_VALUES = {"quiet", "soft", "neutral", "sharp", "strong"}
INTERACTION_ACTION_VOCABULARY = frozenset({
    "agree",
    "challenge",
    "comfort",
    "confront",
    "dismiss",
    "echo",
    "insult",
    "mock",
    "question",
    "support",
    "tease",
})
SEMANTIC_RELATION_VOCABULARY = frozenset({
    "agree",
    "clarify",
    "derail",
    "disagree",
    "echo",
    "escalate",
    "follow_up",
    "joke",
    "nonsense",
    "topic_shift",
})
FORM_VOCABULARY = frozenset({"call_response", "emoji", "fragment", "question", "short", "template"})
_MAX_LABEL_ITEMS = 8
_MAX_STYLE_ANCHOR_LEN = 80
_MAX_SEED_LEN = 80
_BEHAVIOR_STRATEGY_LIMIT = 8
_BASELINE_MIN_SAMPLE = 20
_BEHAVIOR_STRATEGY_MIN_SIMILARITY = 0.3
_BEHAVIOR_STRATEGY_MAX_HITS = 3
_MATCHED_EXAMPLE_LIMIT = 4
_PROFILE_REFRESH_SEC = 20.0
_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)
_VISUAL_SUBJECT_VALUES = frozenset({
    "person",
    "animal",
    "character",
    "object",
    "food",
    "landscape",
    "text",
    "abstract",
    "unknown",
})
_VISUAL_ACTION_VALUES = frozenset({"reaction", "gesture", "pose", "motion", "dialog", "none", "unknown"})
_VISUAL_TONE_VALUES = frozenset({"playful", "cute", "sarcastic", "angry", "sad", "surprised", "neutral", "unknown"})
_VISUAL_TEXT_VALUES = frozenset({"present", "absent", "unreadable", "unknown"})
_VISUAL_CIRCUIT_FAILURE_THRESHOLD = 3
_VISUAL_CIRCUIT_RECOVERY_SEC = 60


class SemanticStyleVisualLabel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    subject: str = "unknown"
    action: str = "unknown"
    tone: str = "unknown"
    text: str = "unknown"


class SemanticStyleVisualCircuitState(BaseModel):
    consecutive_failures: int = 0
    open_until: int = 0


class SemanticStyleVisualCircuitDecision(BaseModel):
    mode: Literal["disabled", "skip", "probe", "allow"]


class SemanticStyleLabel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    version: int = SEMANTIC_STYLE_LABEL_VERSION
    interaction_actions: list[str] = Field(default_factory=list)
    semantic_relations: list[str] = Field(default_factory=list)
    intensity: Literal["quiet", "soft", "neutral", "sharp", "strong"] = "neutral"
    forms: list[str] = Field(default_factory=list)
    visual: SemanticStyleVisualLabel | None = None
    is_reply_pair: bool = False
    transferable: bool = False


class BehaviorStrategy(BaseModel):
    """可复用的真人接话策略：场景→行为→结果，不摘抄原话。"""

    model_config = ConfigDict(extra="ignore")

    scene: str = ""
    action: str = ""
    outcome: str = ""
    trigger: str = ""
    learning_type: Literal["observed", "self_reflection"] = "observed"
    count: int = 1


class SemanticStyleExample(BaseModel):
    model_config = ConfigDict(extra="ignore")

    example_id: str
    created_at: int
    bot_id: int
    group_id: int
    scene: str
    trigger_text: str
    reply_text: str
    label: SemanticStyleLabel
    source_kind: Literal["human_pair", "legacy_unknown"] = "legacy_unknown"
    trigger_user_id: int = 0
    reply_user_id: int = 0
    pair_relation: Literal["quoted", "adjacent"] = "adjacent"
    bot_style_positive: bool = False
    annotation_source: Literal["llm_v2", "legacy_persisted_v1"] = "llm_v2"
    legacy_reuse: Literal["direct", "rewrite", "style", ""] = ""
    legacy_style_anchor: str = ""
    legacy_persona_affinities: list[str] = Field(default_factory=list)
    behavior_strategy: BehaviorStrategy | None = None


class SemanticStyleDirectPair(BaseModel):
    trigger_text: str
    reply_text: str
    source_example_id: str = ""


class SemanticStyleProfile(BaseModel):
    model_config = ConfigDict(extra="ignore")

    bot_id: int
    group_id: int
    scene: str
    style_anchor: str = ""
    direct_examples: list[str] = Field(default_factory=list)
    direct_pairs: list[SemanticStyleDirectPair] = Field(default_factory=list)
    rewrite_seeds: list[str] = Field(default_factory=list)
    interaction_actions: list[str] = Field(default_factory=list)
    semantic_relations: list[str] = Field(default_factory=list)
    persona_affinities: list[str] = Field(default_factory=list)
    intensity_counts: dict[str, int] = Field(default_factory=dict)
    form_counts: dict[str, int] = Field(default_factory=dict)
    bubble_counts: list[int] = Field(default_factory=list)
    segment_char_lengths: list[int] = Field(default_factory=list)
    rhythm_counts: dict[str, int] = Field(default_factory=lambda: {"single": 0, "multi": 0})
    sample_count: int = 0
    common_style_sample_count: int = 0
    bot_style_sample_count: int = 0
    recent_bot_style_sample_count: int = 0
    bot_style_promoted: bool = False
    visual_sample_count: int = 0
    behavior_strategies: list[BehaviorStrategy] = Field(default_factory=list)
    human_only: bool = False
    updated_at: int = 0


class SemanticStyleResolution(BaseModel):
    style_anchor: str = ""
    prompt_block: str = ""
    matched_examples: list[tuple[str, str]] = Field(default_factory=list)
    matched_example_sources: list[SemanticStyleDirectPair] = Field(default_factory=list)
    direct_candidate: str = ""
    source_example_id: str = ""
    baseline_note: str = ""
    behavior_strategies: list[BehaviorStrategy] = Field(default_factory=list)
    style_profile: dict[str, Any] = Field(default_factory=dict)


class SemanticStyleSettings(BaseModel):
    collection_enabled: bool = True
    injection_enabled: bool = True
    direct_enabled: bool = True

    @model_validator(mode="before")
    @classmethod
    def _migrate_legacy_enabled(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        if "enabled" in data and "collection_enabled" not in data and "injection_enabled" not in data:
            legacy = bool(data["enabled"])
            data = {**data, "collection_enabled": legacy, "injection_enabled": legacy}
        legacy_overrides = data.get("overrides")
        if isinstance(legacy_overrides, dict) and "direct_enabled" not in data:
            data = {**data, "direct_enabled": bool(legacy_overrides.get("direct", True))}
        return data

    @property
    def enabled(self) -> bool:
        return self.collection_enabled and self.injection_enabled


class SemanticStyleBackfillCursor(BaseModel):
    """调用方持久化的历史页游标与当日已入队数量。"""

    before_created_at: int = 0
    before_message_id: int = 0
    day_started_at: int = 0
    enqueued_today: int = 0


class SemanticStyleRealtimeBudget(BaseModel):
    day_started_at: int = 0
    admitted_today: int = 0
    sampled_out_today: int = 0
    global_budget_skipped_today: int = 0
    scope_budget_skipped_today: int = 0


class SemanticStyleBackfillBatch(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    jobs: list[WorkJob] = Field(default_factory=list)
    cursor: SemanticStyleBackfillCursor = Field(default_factory=SemanticStyleBackfillCursor)
    deferred: bool = False


_profiles_lock = RLock()
_semantic_data_thread_lock = RLock()
_profiles: dict[tuple[int, int, str], SemanticStyleProfile] = {}
_profiles_revision: tuple[int, int] | None = None
_reload_task: asyncio.Task[None] | None = None
_backfill_task: asyncio.Task[None] | None = None
_startup_bound = False
_labeled_ids_index_built_at = 0.0
_labeled_ids_index: dict[tuple[int, int], set[int]] = {}
_LABELED_IDS_INDEX_TTL_SEC = 5.0
# 群语义采样游标 (time, message_id)：message_id 维度保证同秒内消息不被增量跳过。
_semantic_style_seen_cursors: dict[tuple[int, int], tuple[int, int]] = {}
# 旧版秒级游标（无 message_id）读入时的边界值：视为该秒已全部处理。
_CURSOR_MID_SENTINEL = 2**63 - 1


def labeled_semantic_style_reply_ids(bot_id: int, group_id: int) -> set[int]:
    """已落库语义样本的接话 message_id 集合（TTL 内存索引），供入 LLM 前去重过滤。

    example_id 格式为 ``{group_id}:{message_id}:{bot_id}``，message_id 可能为负
    （新版本 QQ），取中间段解析。重读 examples.jsonl 后重建，避免漏掉并发落库的样本。
    """
    now = time.time()
    global _labeled_ids_index_built_at
    with _semantic_data_thread_lock:
        if now - _labeled_ids_index_built_at > _LABELED_IDS_INDEX_TTL_SEC:
            index: dict[tuple[int, int], set[int]] = {}
            for example in _load_semantic_style_examples(semantic_style_examples_path()):
                if example.annotation_source != "llm_v2":
                    continue
                parts = example.example_id.rsplit(":", 2)
                if len(parts) != 3:
                    continue
                try:
                    message_id = int(parts[1])
                except ValueError:
                    continue
                index.setdefault((example.bot_id, example.group_id), set()).add(message_id)
            _labeled_ids_index.clear()
            _labeled_ids_index.update(index)
            _labeled_ids_index_built_at = now
    return _labeled_ids_index.get((int(bot_id), int(group_id)), set())


def get_semantic_style_group_cursor(bot_id: int, group_id: int) -> tuple[int, int]:
    """读取某群已处理的语义采样消息游标 ``(time, message_id)``。

    旧版仅存秒级时间戳（正整数），读作 ``(time, _CURSOR_MID_SENTINEL)``，
    即该秒视为已全部处理，与历史行为一致。
    """
    scope_key = _semantic_style_group_cursor_key(bot_id, group_id)
    with semantic_style_data_lock():
        cursor = _load_semantic_style_group_cursors().get(scope_key, (0, 0))
    with _profiles_lock:
        _semantic_style_seen_cursors[(int(bot_id), int(group_id))] = cursor
    return cursor


def mark_semantic_style_group_processed(
    bot_id: int,
    group_id: int,
    *,
    processed_at: int,
    processed_message_id: int = 0,
) -> None:
    """原子持久化某群语义采样游标，按 (time, message_id) 只允许向前推进。"""
    if processed_at <= 0:
        return
    next_cursor = (int(processed_at), int(processed_message_id))
    scope_key = _semantic_style_group_cursor_key(bot_id, group_id)
    with semantic_style_data_lock():
        cursors = _load_semantic_style_group_cursors()
        current = cursors.get(scope_key, (0, 0))
        if next_cursor <= current:
            return
        cursors[scope_key] = next_cursor
        _save_semantic_style_group_cursors(cursors)
    with _profiles_lock:
        _semantic_style_seen_cursors[(int(bot_id), int(group_id))] = next_cursor


_direct_quota_windows: dict[tuple[int, int], deque[bool]] = {}
_semantic_style_visual_circuit = SemanticStyleVisualCircuitState()
_DIRECT_QUOTA_WINDOW = 100
_DIRECT_QUOTA_RATE = 0.15
_DIRECT_QUOTA_WARMUP = 20
_DIRECT_PAIR_LIMIT = 6
_DIRECT_TRIGGER_SIMILARITY = 0.6
_DIRECT_REPLY_DEDUP_SIMILARITY = 0.8


def _items(value: object, vocabulary: frozenset[str] | None = None) -> list[str]:
    raw = value if isinstance(value, list) else [value]
    items: list[str] = []
    for item in raw:
        text = str(item or "").strip().lower().replace(" ", "_")
        if text and (vocabulary is None or text in vocabulary) and text not in items:
            items.append(text[:40])
        if len(items) >= _MAX_LABEL_ITEMS:
            break
    return items


def _short_text(value: object, limit: int) -> str:
    return " ".join(str(value or "").strip().split())[:limit]


def parse_semantic_style_visual_label(value: object) -> SemanticStyleVisualLabel:
    raw = value if isinstance(value, dict) else {}

    def controlled(name: str, vocabulary: frozenset[str]) -> str:
        text = str(raw.get(name) or "").strip().lower().replace(" ", "_")
        return text if text in vocabulary else "unknown"

    return SemanticStyleVisualLabel(
        subject=controlled("subject", _VISUAL_SUBJECT_VALUES),
        action=controlled("action", _VISUAL_ACTION_VALUES),
        tone=controlled("tone", _VISUAL_TONE_VALUES),
        text=controlled("text", _VISUAL_TEXT_VALUES),
    )


def semantic_style_visual_circuit_decision(
    state: SemanticStyleVisualCircuitState, *, enabled: bool, now: int
) -> SemanticStyleVisualCircuitDecision:
    if not enabled:
        return SemanticStyleVisualCircuitDecision(mode="disabled")
    if int(state.open_until) > int(now):
        return SemanticStyleVisualCircuitDecision(mode="skip")
    if int(state.open_until):
        return SemanticStyleVisualCircuitDecision(mode="probe")
    return SemanticStyleVisualCircuitDecision(mode="allow")


def record_semantic_style_visual_circuit_failure(
    state: SemanticStyleVisualCircuitState, *, now: int
) -> SemanticStyleVisualCircuitState:
    failures = int(state.consecutive_failures) + 1
    return SemanticStyleVisualCircuitState(
        consecutive_failures=failures,
        open_until=(int(now) + _VISUAL_CIRCUIT_RECOVERY_SEC if failures >= _VISUAL_CIRCUIT_FAILURE_THRESHOLD else 0),
    )


def record_semantic_style_visual_circuit_success(
    state: SemanticStyleVisualCircuitState, *, now: int
) -> SemanticStyleVisualCircuitState:
    del now
    return SemanticStyleVisualCircuitState()


def semantic_style_backfill_remaining_today(cursor: SemanticStyleBackfillCursor, *, now: int) -> int:
    day_started_at = int(now) - int(now) % (24 * 60 * 60)
    used = cursor.enqueued_today if cursor.day_started_at == day_started_at else 0
    return max(0, SEMANTIC_STYLE_BACKFILL_MAX_PER_DAY - int(used))


def build_semantic_style_backfill_batch(
    candidates: Iterable[Mapping[str, object]],
    *,
    cursor: SemanticStyleBackfillCursor | None = None,
    now: int | None = None,
    remaining_today: int | None = None,
    has_pending_new_jobs: bool = False,
) -> SemanticStyleBackfillBatch:
    """将调用方提供的一页历史候选转为有界 work jobs，不负责扫描仓储。"""
    current_time = int(time.time()) if now is None else int(now)
    previous = cursor or SemanticStyleBackfillCursor()
    day_started_at = current_time - current_time % (24 * 60 * 60)
    used_today = previous.enqueued_today if previous.day_started_at == day_started_at else 0
    capacity = semantic_style_backfill_remaining_today(previous, now=current_time)
    if remaining_today is not None:
        capacity = min(capacity, max(0, int(remaining_today)))
    next_cursor = previous.model_copy(update={"day_started_at": day_started_at, "enqueued_today": used_today})
    if has_pending_new_jobs or capacity <= 0:
        return SemanticStyleBackfillBatch(cursor=next_cursor, deferred=True)

    cutoff = current_time - SEMANTIC_STYLE_BACKFILL_WINDOW_SEC
    jobs: list[WorkJob] = []
    for item in candidates:
        message_id = int(item.get("message_id") or 0)
        created_at = int(item.get("created_at") or 0)
        if message_id <= 0:
            continue
        candidate_cursor = next_cursor.model_copy(
            update={"before_created_at": created_at, "before_message_id": message_id}
        )
        if created_at <= 0:
            next_cursor = candidate_cursor
            continue
        if created_at < cutoff or created_at > current_time:
            next_cursor = candidate_cursor
            continue
        trigger = _short_text(item.get("trigger_text"), 240)
        reply = _short_text(item.get("reply_text"), 240)
        bot_id = int(item.get("bot_id") or 0)
        group_id = int(item.get("group_id") or 0)
        if not trigger or not reply or bot_id <= 0 or group_id <= 0:
            next_cursor = candidate_cursor
            continue
        if not semantic_style_collection_enabled(bot_id=bot_id, group_id=group_id):
            next_cursor = candidate_cursor
            continue
        job = WorkJob.create(
            kind="repeater.semantic_style.backfill",
            payload={
                "example_id": str(item.get("example_id") or f"{group_id}:{message_id}:{bot_id}"),
                "message_id": message_id,
                "created_at": created_at,
                "expires_at": current_time + SEMANTIC_STYLE_BACKFILL_JOB_TTL_SEC,
                "bot_id": bot_id,
                "group_id": group_id,
                "scene": str(item.get("scene") or "group_chat"),
                "trigger_text": trigger,
                "reply_text": reply,
                "trigger_user_id": int(item.get("trigger_user_id") or 0),
                "reply_user_id": int(item.get("reply_user_id") or 0),
                "source": "backfill",
            },
            idempotency_key=f"repeater.semantic_style.backfill:{group_id}:{message_id}:{bot_id}",
        )
        jobs.append(job)
        next_cursor = candidate_cursor
        if len(jobs) >= capacity:
            break

    next_cursor = next_cursor.model_copy(update={"enqueued_today": used_today + len(jobs)})
    return SemanticStyleBackfillBatch(
        jobs=jobs,
        cursor=next_cursor,
        deferred=len(jobs) >= capacity,
    )


def semantic_style_backfill_message_id(*, group_id: int, bot_id: int, created_at: int, reply_text: str) -> int:
    """为历史 Message 缺少原始 message_id 的场景生成稳定的回填标识。"""
    digest = hashlib.blake2s(
        f"{int(group_id)}:{int(bot_id)}:{int(created_at)}:{reply_text}".encode(), digest_size=4
    ).digest()
    return int.from_bytes(digest, "big")


def semantic_style_backfill_candidate_allowed(
    candidate: Mapping[str, object], cursor: SemanticStyleBackfillCursor
) -> bool:
    before_time = int(cursor.before_created_at)
    if before_time <= 0:
        return True
    created_at = int(candidate.get("created_at") or 0)
    message_id = int(candidate.get("message_id") or 0)
    return created_at < before_time or (created_at == before_time and message_id < int(cursor.before_message_id))


def semantic_style_answer_samples(answers: Iterable[object]) -> set[str]:
    samples: set[str] = set()
    for answer in answers:
        for message in getattr(answer, "messages", ()) or ():
            text = str(message or "").strip()
            if text:
                samples.add(text)
                samples.add(text.removeprefix("牛牛").strip())
    return samples


def is_human_semantic_style_pair(*, trigger_user_id: object, reply_user_id: object, bot_id: object) -> bool:
    """真人接话参考只接受两端都非本机或协作 bot 的消息。"""
    try:
        trigger_id = int(trigger_user_id)
        reply_id = int(reply_user_id)
        self_id = int(bot_id)
    except (TypeError, ValueError):
        return False
    if trigger_id <= 0 or reply_id <= 0 or self_id <= 0:
        return False
    from pallas.product.llm.sender_identity import is_peer_bot

    return trigger_id != self_id and reply_id != self_id and not is_peer_bot(trigger_id) and not is_peer_bot(reply_id)


async def collect_semantic_style_backfill_candidates(
    *,
    now: int | None = None,
    bot_ids: Iterable[int] | None = None,
    cursor: SemanticStyleBackfillCursor | None = None,
) -> list[dict[str, object]]:
    """历史数据缺少可靠作者来源，不能作为真人接话参考。"""
    if not SEMANTIC_STYLE_BACKFILL_ENABLED:
        return []
    current_time = int(time.time()) if now is None else int(now)
    cutoff = current_time - SEMANTIC_STYLE_BACKFILL_WINDOW_SEC
    ids = {int(item) for item in (bot_ids or ()) if int(item) > 0}
    if bot_ids is None:
        for key, bot in get_bots().items():
            value = getattr(bot, "self_id", key)
            try:
                ids.add(int(value))
            except (TypeError, ValueError):
                continue
    if not ids:
        return []

    message_repo = make_message_repository()
    context_repo = make_local_context_repository()
    list_groups = getattr(message_repo, "list_recent_group_ids_for_bot", None)
    if not callable(list_groups):
        return []
    list_answers = getattr(context_repo, "list_answers_for_group_since", None)
    if not callable(list_answers):
        return []

    previous = cursor or SemanticStyleBackfillCursor()
    candidates: list[dict[str, object]] = []
    seen: set[tuple[int, int, int]] = set()
    for bot_id in sorted(ids):
        try:
            group_ids = await list_groups(
                bot_id,
                since_time=cutoff,
                limit=_SEMANTIC_STYLE_BACKFILL_GROUP_LIMIT,
            )
        except Exception as exc:
            logger.warning("Repeater semantic style backfill could not list groups for bot [{}]: [{}]", bot_id, exc)
            continue
        for group_id in group_ids:
            gid = int(group_id)
            if not semantic_style_collection_enabled(bot_id=bot_id, group_id=gid):
                continue
            try:
                answers = await list_answers(gid, cutoff)
            except Exception as exc:
                logger.warning("Repeater semantic style backfill could not list answers for group [{}]: [{}]", gid, exc)
                continue
            reply_samples = semantic_style_answer_samples(answers)
            if not reply_samples:
                continue
            before_time = current_time + 1
            while before_time > cutoff:
                try:
                    messages = await message_repo.find_recent_in_group(
                        gid,
                        before_time=before_time,
                        limit=_SEMANTIC_STYLE_BACKFILL_PAGE_SIZE,
                    )
                except Exception as exc:
                    logger.warning(
                        "Repeater semantic style backfill could not list messages for group [{}]: [{}]", gid, exc
                    )
                    break
                ordered = list(messages)
                if not ordered:
                    break
                for index, reply_message in enumerate(ordered[1:], start=1):
                    predecessor = ordered[index - 1]
                    created_at = int(getattr(reply_message, "time", 0) or 0)
                    if created_at < cutoff:
                        continue
                    if int(getattr(reply_message, "bot_id", 0) or 0) != bot_id:
                        continue
                    reply_text = _short_text(
                        getattr(reply_message, "plain_text", "") or getattr(reply_message, "raw_message", ""), 240
                    )
                    if not reply_text or reply_text not in reply_samples:
                        continue
                    trigger_text = _short_text(
                        getattr(predecessor, "plain_text", "") or getattr(predecessor, "raw_message", ""), 240
                    )
                    if not trigger_text:
                        continue
                    message_id = semantic_style_backfill_message_id(
                        group_id=gid,
                        bot_id=bot_id,
                        created_at=created_at,
                        reply_text=reply_text,
                    )
                    key = gid, bot_id, message_id
                    candidate = {
                        "example_id": f"{gid}:{message_id}:{bot_id}",
                        "message_id": message_id,
                        "created_at": created_at,
                        "bot_id": bot_id,
                        "group_id": gid,
                        "scene": "group_chat",
                        "trigger_text": trigger_text,
                        "reply_text": reply_text,
                        "trigger_user_id": int(getattr(predecessor, "user_id", 0) or 0),
                        "reply_user_id": int(getattr(reply_message, "user_id", 0) or 0),
                    }
                    if key not in seen and semantic_style_backfill_candidate_allowed(candidate, previous):
                        seen.add(key)
                        candidates.append(candidate)
                oldest = min(int(getattr(item, "time", 0) or 0) for item in ordered)
                if len(ordered) < _SEMANTIC_STYLE_BACKFILL_PAGE_SIZE or oldest <= cutoff:
                    break
                before_time = oldest
                await asyncio.sleep(0)
    return sorted(candidates, key=lambda item: (int(item["created_at"]), int(item["message_id"])), reverse=True)


def parse_semantic_style_label(value: object) -> SemanticStyleLabel:
    raw = value if isinstance(value, dict) else {}
    intensity = str(raw.get("intensity") or "").strip().lower()
    return SemanticStyleLabel(
        interaction_actions=_items(raw.get("interaction_actions"), INTERACTION_ACTION_VOCABULARY),
        semantic_relations=_items(raw.get("semantic_relations"), SEMANTIC_RELATION_VOCABULARY),
        intensity=intensity if intensity in _INTENSITY_VALUES else "neutral",
        forms=_items(raw.get("forms"), FORM_VOCABULARY),
        visual=parse_semantic_style_visual_label(raw.get("visual")) if isinstance(raw.get("visual"), dict) else None,
        is_reply_pair=raw.get("is_reply_pair") is True,
        transferable=raw.get("transferable") is True,
    )


def parse_behavior_strategy(value: object) -> BehaviorStrategy | None:
    raw = value if isinstance(value, dict) else {}
    scene = _short_text(raw.get("scene"), _MAX_SEED_LEN)
    action = _short_text(raw.get("action"), _MAX_SEED_LEN)
    if not scene or not action:
        return None
    learning_type = str(raw.get("learning_type") or "").strip().lower()
    return BehaviorStrategy(
        scene=scene,
        action=action,
        outcome=_short_text(raw.get("outcome"), _MAX_SEED_LEN),
        learning_type="self_reflection" if learning_type == "self_reflection" else "observed",
    )


def semantic_style_base_dir() -> Path:
    env_dir = str(os.environ.get("PALLAS_DATA_DIR") or "").strip()
    root = Path(env_dir) if env_dir else plugin_data_dir("pb_webui", create=True)
    path = root / "repeater_semantic_style"
    path.mkdir(parents=True, exist_ok=True)
    return path


def semantic_style_examples_path() -> Path:
    return semantic_style_base_dir() / "examples.jsonl"


def semantic_style_profiles_path() -> Path:
    return semantic_style_base_dir() / "profiles.json"


def semantic_style_data_lock_path() -> Path:
    return semantic_style_base_dir() / "semantic_style_data.lock"


def semantic_style_group_cursor_path() -> Path:
    return semantic_style_base_dir() / "semantic_style_group_cursors.json"


def _semantic_style_group_cursor_key(bot_id: int, group_id: int) -> str:
    return f"{int(bot_id)}:{int(group_id)}"


def _parse_semantic_style_cursor(value: object) -> tuple[int, int] | None:
    """游标值兼容两种形态：正整数（旧版秒级）与 ``[time, message_id]``。"""
    if isinstance(value, int | float):
        parsed_time = int(value)
        if parsed_time <= 0:
            return None
        return (parsed_time, _CURSOR_MID_SENTINEL)
    if isinstance(value, list) and len(value) == 2:
        try:
            parsed_time = int(value[0])
            parsed_mid = int(value[1])
        except (TypeError, ValueError):
            return None
        if parsed_time <= 0:
            return None
        return (parsed_time, parsed_mid)
    return None


def _load_semantic_style_group_cursors() -> dict[str, tuple[int, int]]:
    try:
        raw = json.loads(semantic_style_group_cursor_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    cursors: dict[str, tuple[int, int]] = {}
    for key, value in raw.items():
        cursor = _parse_semantic_style_cursor(value)
        if cursor is not None:
            cursors[str(key)] = cursor
    return cursors


def _save_semantic_style_group_cursors(cursors: dict[str, tuple[int, int]]) -> None:
    payload = {key: [cursor[0], cursor[1]] for key, cursor in cursors.items()}
    atomic_write_text(
        semantic_style_group_cursor_path(),
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n",
    )


def semantic_style_label_budget_path() -> Path:
    """语义风格每日 LLM 标注预算计数文件路径（按天记录已提交次数）。"""
    return semantic_style_base_dir() / "semantic_style_label_budget.json"


def _semantic_label_budget_state() -> dict[str, Any]:
    try:
        raw = json.loads(semantic_style_label_budget_path().read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def semantic_label_budget_used_today(*, day_key: int | None = None) -> int:
    """今日已提交的语义风格 LLM 标注次数（跨进程按天持久化计数）。"""
    if day_key is None:
        day_key = int(time.time() // 86400)
    state = _semantic_label_budget_state()
    return int(state.get(str(day_key)) or 0)


def record_semantic_label_budget(n: int = 1) -> None:
    """累加一次语义风格 LLM 标注提交计数（按天分桶，供预算闸消费侧判断）。"""
    if n <= 0:
        return
    day_key = int(time.time() // 86400)
    state = _semantic_label_budget_state()
    state[str(day_key)] = int(state.get(str(day_key)) or 0) + n
    try:
        tmp = semantic_style_label_budget_path().with_suffix(".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        Path(tmp).replace(semantic_style_label_budget_path())
    except Exception as exc:
        logger.warning("记录语义标注预算失败：{}", exc)


def claim_semantic_label_budget(n: int = 1) -> bool:
    """在发起语义标注请求前原子预占每日预算。"""
    if n <= 0:
        return True
    from pallas.product.llm.config import get_llm_config

    limit = max(0, int(getattr(get_llm_config(), "llm_semantic_style_realtime_daily_limit", 0) or 0))
    day_key = str(int(time.time() // 86400))
    with semantic_style_data_lock():
        state = _semantic_label_budget_state()
        used = int(state.get(day_key) or 0)
        if limit > 0 and used + n > limit:
            return False
        state[day_key] = used + n
        try:
            tmp = semantic_style_label_budget_path().with_suffix(".tmp")
            tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
            Path(tmp).replace(semantic_style_label_budget_path())
        except Exception as exc:
            logger.warning("记录语义标注预算失败：{}", exc)
            return False
    return True


def semantic_label_budget_ok(*, day_key: int | None = None) -> bool:
    """语义风格每日 LLM 标注预算闸：消费侧检查今日累计是否已达上限。

    上限配置 ``llm_semantic_style_realtime_daily_limit``，默认 5000 次/天。
    达到上限返回 False，由调用方跳过本次标注（软上限，不阻塞入队、不影响游标轮转）。
    """
    from pallas.product.llm.config import get_llm_config

    limit = max(0, int(getattr(get_llm_config(), "llm_semantic_style_realtime_daily_limit", 0) or 0))
    if limit <= 0:
        return True
    return semantic_label_budget_used_today(day_key=day_key) < limit


def semantic_style_legacy_migration_marker_path() -> Path:
    return semantic_style_base_dir() / "legacy_profiles_migrated_v2.json"


@contextmanager
def semantic_style_data_lock():
    with _semantic_data_thread_lock, interprocess_file_lock(semantic_style_data_lock_path()):
        yield


def semantic_style_backfill_cursor_path(*, bot_id: int | None = None, group_id: int | None = None) -> Path:
    scope = _semantic_style_scope(bot_id, group_id)
    if scope is None:
        return semantic_style_base_dir() / "backfill_cursor.json"
    return semantic_style_base_dir() / "backfill_cursors" / str(scope[0]) / f"{scope[1]}.json"


def _semantic_style_scope(bot_id: int | None, group_id: int | None) -> tuple[int, int] | None:
    if bot_id is None and group_id is None:
        return None
    if bot_id is None or group_id is None:
        raise ValueError("bot_id 和 group_id 必须同时提供")
    bot = int(bot_id)
    group = int(group_id)
    if bot <= 0 or group <= 0:
        raise ValueError("bot_id 和 group_id 必须为正整数")
    return bot, group


def _in_semantic_style_scope(
    example: SemanticStyleExample | SemanticStyleProfile, scope: tuple[int, int] | None
) -> bool:
    return scope is None or (example.bot_id, example.group_id) == scope


def semantic_style_settings_path(*, bot_id: int | None = None, group_id: int | None = None) -> Path:
    scope = _semantic_style_scope(bot_id, group_id)
    if scope is None:
        return semantic_style_base_dir() / "settings.json"
    return semantic_style_base_dir() / "settings" / str(scope[0]) / f"{scope[1]}.json"


def load_semantic_style_settings(*, bot_id: int | None = None, group_id: int | None = None) -> SemanticStyleSettings:
    scope = _semantic_style_scope(bot_id, group_id)
    try:
        raw = json.loads(semantic_style_settings_path(bot_id=bot_id, group_id=group_id).read_text(encoding="utf-8"))
        return SemanticStyleSettings.model_validate(raw)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return load_semantic_style_settings() if scope is not None else SemanticStyleSettings()


def _save_semantic_style_settings(
    settings: SemanticStyleSettings, *, bot_id: int | None = None, group_id: int | None = None
) -> None:
    path = semantic_style_settings_path(bot_id=bot_id, group_id=group_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(settings.model_dump_json(), encoding="utf-8")
    tmp.replace(path)


def semantic_style_status(*, bot_id: int | None = None, group_id: int | None = None) -> dict[str, Any]:
    scope = _semantic_style_scope(bot_id, group_id)
    settings = load_semantic_style_settings(bot_id=bot_id, group_id=group_id)
    examples = _load_semantic_style_examples(semantic_style_examples_path())
    profiles = _load_profiles(semantic_style_profiles_path())
    scoped_examples = [example for example in examples if _in_semantic_style_scope(example, scope)]
    scoped_profiles = [profile for profile in profiles.values() if _in_semantic_style_scope(profile, scope)]
    return {
        "enabled": settings.enabled,
        "collection_enabled": settings.collection_enabled,
        "injection_enabled": settings.injection_enabled,
        "direct_enabled": settings.direct_enabled,
        "example_count": len(scoped_examples),
        "profile_count": len(scoped_profiles),
        "backfill_cursor": load_semantic_style_backfill_cursor(bot_id=bot_id, group_id=group_id).model_dump(
            mode="json"
        ),
    }


def set_semantic_style_direct_enabled(
    enabled: bool, *, bot_id: int | None = None, group_id: int | None = None
) -> dict[str, Any]:
    settings = load_semantic_style_settings(bot_id=bot_id, group_id=group_id).model_copy(
        update={"direct_enabled": bool(enabled)}
    )
    _save_semantic_style_settings(settings, bot_id=bot_id, group_id=group_id)
    return semantic_style_status(bot_id=bot_id, group_id=group_id)


def set_semantic_style_enabled(
    enabled: bool, *, bot_id: int | None = None, group_id: int | None = None
) -> dict[str, Any]:
    value = bool(enabled)
    settings = load_semantic_style_settings(bot_id=bot_id, group_id=group_id).model_copy(
        update={"collection_enabled": value, "injection_enabled": value}
    )
    _save_semantic_style_settings(settings, bot_id=bot_id, group_id=group_id)
    return semantic_style_status(bot_id=bot_id, group_id=group_id)


def set_semantic_style_governance(
    *, bot_id: int | None = None, group_id: int | None = None, collection_enabled: bool, injection_enabled: bool
) -> dict[str, Any]:
    settings = load_semantic_style_settings(bot_id=bot_id, group_id=group_id).model_copy(
        update={
            "collection_enabled": bool(collection_enabled),
            "injection_enabled": bool(injection_enabled),
        }
    )
    _save_semantic_style_settings(settings, bot_id=bot_id, group_id=group_id)
    return semantic_style_status(bot_id=bot_id, group_id=group_id)


def clear_semantic_style_data(
    *, bot_id: int | None = None, group_id: int | None = None, continue_learning: bool = True
) -> dict[str, Any]:
    scope = _semantic_style_scope(bot_id, group_id)
    with semantic_style_data_lock():
        examples = load_examples_with_legacy_migration_locked()
        retained = [example for example in examples if not _in_semantic_style_scope(example, scope)] if scope else []
        _write_semantic_style_examples(semantic_style_examples_path(), retained)
        _write_profiles(_rebuild_profiles(retained, now=int(time.time())))
        save_semantic_style_backfill_cursor(SemanticStyleBackfillCursor(), bot_id=bot_id, group_id=group_id)
        settings = load_semantic_style_settings(bot_id=bot_id, group_id=group_id).model_copy(
            update={"collection_enabled": bool(continue_learning)}
        )
        _save_semantic_style_settings(settings, bot_id=bot_id, group_id=group_id)
    return semantic_style_status(bot_id=bot_id, group_id=group_id)


def rebuild_semantic_style_profiles(*, bot_id: int | None = None, group_id: int | None = None) -> dict[str, Any]:
    with semantic_style_data_lock():
        examples = load_examples_with_legacy_migration_locked()
        _write_profiles(_rebuild_profiles(examples, now=int(time.time())))
    return semantic_style_status(bot_id=bot_id, group_id=group_id)


def semantic_style_quality(*, bot_id: int | None = None, group_id: int | None = None) -> dict[str, Any]:
    scope = _semantic_style_scope(bot_id, group_id)
    examples = _load_semantic_style_examples(semantic_style_examples_path())
    scoped_examples = [example for example in examples if _in_semantic_style_scope(example, scope)]
    return {
        **semantic_style_status(bot_id=bot_id, group_id=group_id),
        "label_version": SEMANTIC_STYLE_LABEL_VERSION,
        "positive_bot_style_count": sum(example.bot_style_positive for example in scoped_examples),
    }


def recover_semantic_style_data(*, bot_id: int | None = None, group_id: int | None = None) -> dict[str, Any]:
    with semantic_style_data_lock():
        examples = load_examples_with_legacy_migration_locked()
        _write_semantic_style_examples(semantic_style_examples_path(), examples)
        _write_profiles(_rebuild_profiles(examples, now=int(time.time())))
    refresh_semantic_style_cache(force=True)
    return semantic_style_status(bot_id=bot_id, group_id=group_id)


def load_semantic_style_backfill_cursor(
    *, bot_id: int | None = None, group_id: int | None = None
) -> SemanticStyleBackfillCursor:
    try:
        raw = json.loads(
            semantic_style_backfill_cursor_path(bot_id=bot_id, group_id=group_id).read_text(encoding="utf-8")
        )
        return SemanticStyleBackfillCursor.model_validate(raw)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return SemanticStyleBackfillCursor()


def save_semantic_style_backfill_cursor(
    cursor: SemanticStyleBackfillCursor, *, bot_id: int | None = None, group_id: int | None = None
) -> None:
    path = semantic_style_backfill_cursor_path(bot_id=bot_id, group_id=group_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(cursor.model_dump_json(), encoding="utf-8")
    tmp.replace(path)


def _revision(path: Path) -> tuple[int, int]:
    try:
        stat = path.stat()
    except OSError:
        return (0, 0)
    return int(stat.st_mtime_ns), int(stat.st_size)


def _profile_key(bot_id: int, group_id: int, scene: str) -> tuple[int, int, str]:
    return int(bot_id), int(group_id), str(scene or "default").strip().lower() or "default"


def _load_profiles(path: Path) -> dict[tuple[int, int, str], SemanticStyleProfile]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    rows = raw.get("profiles") if isinstance(raw, dict) else raw
    if not isinstance(rows, list):
        return {}
    profiles: dict[tuple[int, int, str], SemanticStyleProfile] = {}
    for item in rows:
        try:
            profile = SemanticStyleProfile.model_validate(item)
        except Exception:
            continue
        profiles[_profile_key(profile.bot_id, profile.group_id, profile.scene)] = profile
    return profiles


def refresh_semantic_style_cache(*, force: bool = False) -> None:
    global _profiles_revision, _profiles
    path = semantic_style_profiles_path()
    revision = _revision(path)
    with _profiles_lock:
        if not force and _profiles_revision == revision:
            return
        _profiles = _load_profiles(path)
        _profiles_revision = revision


def clear_semantic_style_cache_for_tests() -> None:
    global _profiles_revision, _profiles
    with _profiles_lock:
        _profiles = {}
        _profiles_revision = None


def clear_semantic_style_direct_quota_for_tests() -> None:
    with _profiles_lock:
        _direct_quota_windows.clear()


def _write_profiles(profiles: dict[tuple[int, int, str], SemanticStyleProfile]) -> None:
    global _profiles_revision, _profiles
    path = semantic_style_profiles_path()
    payload = {"profiles": [item.model_dump(mode="json") for item in profiles.values()]}
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)
    with _profiles_lock:
        _profiles = dict(profiles)
        _profiles_revision = _revision(path)


def _popular(values: list[str], limit: int = 3) -> list[str]:
    return [item for item, _count in Counter(values).most_common(limit)]


def deterministic_reply_shape(reply_text: str) -> tuple[int, list[int], str]:
    segments = [item.strip() for item in str(reply_text or "").splitlines() if item.strip()]
    if not segments:
        segments = [str(reply_text or "").strip()] if str(reply_text or "").strip() else []
    bubble_count = len(segments)
    return bubble_count, [len(item) for item in segments], "multi" if bubble_count > 1 else "single"


def _build_profile(
    example: SemanticStyleExample,
    existing: SemanticStyleProfile | None,
    *,
    now: int | None = None,
    is_bot_reply: bool = False,
) -> SemanticStyleProfile:
    label = example.label
    prior_actions = list(existing.interaction_actions) if existing else []
    prior_relations = list(existing.semantic_relations) if existing else []
    prior_affinities = list(existing.persona_affinities) if existing else []
    direct_examples = list(existing.direct_examples) if existing else []
    direct_pairs = list(existing.direct_pairs) if existing else []
    rewrite_seeds = list(existing.rewrite_seeds) if existing else []
    reply_text = _short_text(example.reply_text, _MAX_SEED_LEN)
    bubble_count, segment_char_lengths, rhythm = deterministic_reply_shape(example.reply_text)
    bubble_counts = list(existing.bubble_counts) if existing else []
    prior_segment_lengths = list(existing.segment_char_lengths) if existing else []
    rhythm_counts = dict(existing.rhythm_counts) if existing else {"single": 0, "multi": 0}
    if bubble_count:
        bubble_counts.append(bubble_count)
        prior_segment_lengths.extend(segment_char_lengths)
        rhythm_counts[rhythm] = int(rhythm_counts.get(rhythm) or 0) + 1
    bot_style_sample_count = (existing.bot_style_sample_count if existing else 0) + int(example.bot_style_positive)
    recent_bot_style_sample_count = (existing.recent_bot_style_sample_count if existing else 0) + int(
        example.bot_style_positive and (now is None or example.created_at >= now - BOT_STYLE_RECENT_SEC)
    )
    bot_style_promoted = (
        bot_style_sample_count >= BOT_STYLE_PROMOTION_SAMPLE_COUNT
        and recent_bot_style_sample_count >= BOT_STYLE_PROMOTION_RECENT_SAMPLE_COUNT
    )
    if example.source_kind == "human_pair" and reply_text and not is_bot_reply:
        direct_examples = [item for item in direct_examples if item != reply_text]
        direct_examples.append(reply_text)
        pair = SemanticStyleDirectPair(
            trigger_text=_short_text(example.trigger_text, 240),
            reply_text=reply_text,
            source_example_id=example.example_id,
        )
        direct_pairs = [item for item in direct_pairs if item != pair]
        direct_pairs.append(pair)
    elif reply_text and example.legacy_reuse != "style":
        rewrite_seeds = [item for item in rewrite_seeds if item != reply_text]
        rewrite_seeds.append(reply_text)
    intensity_counts = dict(existing.intensity_counts) if existing else {}
    intensity_counts[label.intensity] = int(intensity_counts.get(label.intensity) or 0) + 1
    form_counts = dict(existing.form_counts) if existing else {}
    for form in label.forms:
        form_counts[form] = int(form_counts.get(form) or 0) + 1
    strategies = list(existing.behavior_strategies) if existing else []
    if example.behavior_strategy is not None and example.behavior_strategy.action:
        strategy = example.behavior_strategy
        if not strategy.trigger:
            strategy = strategy.model_copy(update={"trigger": _short_text(example.trigger_text, _MAX_SEED_LEN)})
        if example.bot_style_positive or is_bot_reply:
            strategy = strategy.model_copy(update={"learning_type": "self_reflection"})
        merged = False
        for index, prior in enumerate(strategies):
            if prior.learning_type == strategy.learning_type and prior.action == strategy.action:
                strategies[index] = prior.model_copy(update={"count": prior.count + 1})
                merged = True
                break
        if not merged:
            strategies.append(strategy)
        strategies = strategies[-_BEHAVIOR_STRATEGY_LIMIT:]
    return SemanticStyleProfile(
        bot_id=example.bot_id,
        group_id=example.group_id,
        scene=example.scene,
        style_anchor=example.legacy_style_anchor or (existing.style_anchor if existing else ""),
        direct_examples=direct_examples[-3:],
        direct_pairs=direct_pairs[-_DIRECT_PAIR_LIMIT:],
        rewrite_seeds=rewrite_seeds[-3:],
        interaction_actions=_popular([*prior_actions, *label.interaction_actions]),
        semantic_relations=_popular([*prior_relations, *label.semantic_relations]),
        persona_affinities=_popular([*prior_affinities, *example.legacy_persona_affinities]),
        intensity_counts=intensity_counts,
        form_counts=form_counts,
        bubble_counts=bubble_counts[-100:],
        segment_char_lengths=prior_segment_lengths[-300:],
        rhythm_counts=rhythm_counts,
        sample_count=(existing.sample_count if existing else 0) + 1,
        common_style_sample_count=(existing.common_style_sample_count if existing else 0)
        + int(not example.bot_style_positive),
        bot_style_sample_count=bot_style_sample_count,
        recent_bot_style_sample_count=recent_bot_style_sample_count,
        bot_style_promoted=bot_style_promoted,
        visual_sample_count=(existing.visual_sample_count if existing else 0) + int(label.visual is not None),
        behavior_strategies=strategies,
        human_only=True,
        updated_at=example.created_at,
    )


def persist_semantic_style_examples(
    new_examples: list[SemanticStyleExample],
) -> dict[tuple[int, int, str], SemanticStyleProfile]:
    """批量落盘语义风格样本：按 example_id 幂等去重，一次重建全部 profiles。

    同一 job 重复处理（跨天 idempotency_key 变化、异常重放等）会带来重复 example_id；
    这里按 example_id 去重，避免 profiles.json 的 sample_count 虚增与 direct_pairs 重复。
    相比逐条 persist_semantic_style_example，只做一次文件读写与 profiles 重建。
    """
    with semantic_style_data_lock():
        examples = load_examples_with_legacy_migration_locked()
        existing_ids = {item.example_id for item in examples}
        merged = {item.example_id: item for item in examples}
        for example in new_examples:
            if example.example_id in existing_ids:
                continue
            existing_ids.add(example.example_id)
            merged[example.example_id] = example
        updated = sorted(merged.values(), key=lambda item: (item.created_at, item.example_id))
        _write_semantic_style_examples(semantic_style_examples_path(), updated)
        profiles = _rebuild_profiles(updated, now=int(time.time()))
        _write_profiles(profiles)
        return profiles


def persist_semantic_style_example(example: SemanticStyleExample) -> SemanticStyleProfile | None:
    with semantic_style_data_lock():
        examples = load_examples_with_legacy_migration_locked()
        examples.append(example)
        _write_semantic_style_examples(semantic_style_examples_path(), examples)
        profiles = _rebuild_profiles(examples, now=int(time.time()))
        _write_profiles(profiles)
        return profiles.get(_profile_key(example.bot_id, example.group_id, example.scene))


def is_positive_bot_style_outcome(
    *,
    reply_created_at: int,
    following_created_at: int,
    following_is_bot: bool,
    following_text: str,
    following_is_banned: bool = False,
    following_has_negative_feedback: bool = False,
) -> bool:
    return (
        not following_is_bot
        and not following_is_banned
        and not following_has_negative_feedback
        and bool(_short_text(following_text, 240))
        and 0 <= int(following_created_at) - int(reply_created_at) <= BOT_STYLE_POSITIVE_REPLY_SEC
    )


def record_bot_style_outcome(
    example: SemanticStyleExample,
    *,
    bot_reply_created_at: int | None = None,
    following_created_at: int,
    following_is_bot: bool,
    following_text: str,
    following_is_banned: bool = False,
    following_has_negative_feedback: bool = False,
) -> SemanticStyleProfile | None:
    if not is_positive_bot_style_outcome(
        reply_created_at=int(bot_reply_created_at if bot_reply_created_at is not None else example.created_at),
        following_created_at=following_created_at,
        following_is_bot=following_is_bot,
        following_text=following_text,
        following_is_banned=following_is_banned,
        following_has_negative_feedback=following_has_negative_feedback,
    ):
        return None
    with semantic_style_data_lock():
        positive_example = example.model_copy(update={"bot_style_positive": True})
        examples_path = semantic_style_examples_path()
        updated_examples: list[SemanticStyleExample] = []
        found = False
        for stored_example in load_examples_with_legacy_migration_locked():
            if stored_example.example_id != positive_example.example_id:
                updated_examples.append(stored_example)
                continue
            if not found:
                updated_examples.append(positive_example)
                found = True
        if not found:
            return None
        _write_semantic_style_examples(examples_path, updated_examples)
        profiles = _rebuild_profiles(updated_examples, now=max(item.created_at for item in updated_examples))
        _write_profiles(profiles)
        return profiles.get(_profile_key(positive_example.bot_id, positive_example.group_id, positive_example.scene))


def find_semantic_style_example(
    *, example_id: str, bot_id: int, group_id: int, scene: str
) -> SemanticStyleExample | None:
    for example in reversed(_load_semantic_style_examples(semantic_style_examples_path())):
        if (
            example.example_id == str(example_id)
            and example.bot_id == int(bot_id)
            and example.group_id == int(group_id)
            and example.scene == str(scene)
        ):
            return example
    return None


def _load_semantic_style_examples(path: Path) -> list[SemanticStyleExample]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    examples: list[SemanticStyleExample] = []
    for line in lines:
        try:
            raw = json.loads(line)
            if isinstance(raw, dict):
                raw.setdefault("source_kind", "legacy_unknown")
            label_raw = raw.get("label") if isinstance(raw, dict) else None
            if isinstance(label_raw, dict) and int(label_raw.get("version") or 1) < SEMANTIC_STYLE_LABEL_VERSION:
                legacy_reuse = str(label_raw.get("reuse") or "").strip().lower()
                if legacy_reuse in {"direct", "rewrite", "style"}:
                    raw["annotation_source"] = "legacy_persisted_v1"
                    raw["legacy_reuse"] = legacy_reuse
                    raw["legacy_style_anchor"] = _short_text(label_raw.get("style_anchor"), _MAX_STYLE_ANCHOR_LEN)
                    raw["legacy_persona_affinities"] = _items(label_raw.get("persona_affinities"))
            example = SemanticStyleExample.model_validate(raw)
        except (json.JSONDecodeError, ValueError, TypeError):
            continue
        examples.append(example.model_copy(update={"label": parse_semantic_style_label(example.label.model_dump())}))
    return examples


def migrate_legacy_profiles_to_examples(
    examples: list[SemanticStyleExample],
    profiles: dict[tuple[int, int, str], SemanticStyleProfile],
    *,
    now: int,
) -> list[SemanticStyleExample]:
    migrated = list(examples)
    known_ids = {item.example_id for item in migrated}
    for profile in profiles.values():
        pairs = list(profile.direct_pairs)
        if not pairs:
            pairs = [SemanticStyleDirectPair(trigger_text="", reply_text=text) for text in profile.direct_examples]
        if not pairs and (profile.style_anchor or profile.persona_affinities):
            pairs = [SemanticStyleDirectPair(trigger_text="", reply_text="")]
        for index, pair in enumerate(pairs):
            digest = hashlib.blake2s(
                f"{profile.bot_id}:{profile.group_id}:{profile.scene}:{pair.trigger_text}:{pair.reply_text}".encode(),
                digest_size=8,
            ).hexdigest()
            example_id = f"legacy-profile-v1:{digest}"
            if example_id in known_ids:
                continue
            migrated.append(
                SemanticStyleExample(
                    example_id=example_id,
                    created_at=max(int(profile.updated_at or 0), now),
                    bot_id=profile.bot_id,
                    group_id=profile.group_id,
                    scene=profile.scene,
                    trigger_text=pair.trigger_text,
                    reply_text=pair.reply_text,
                    label=SemanticStyleLabel(),
                    source_kind="legacy_unknown",
                    annotation_source="legacy_persisted_v1",
                    legacy_reuse="direct" if pair.reply_text else "style",
                    legacy_style_anchor=profile.style_anchor if index == 0 else "",
                    legacy_persona_affinities=profile.persona_affinities if index == 0 else [],
                )
            )
            known_ids.add(example_id)
    return migrated


def load_examples_with_legacy_migration_locked() -> list[SemanticStyleExample]:
    examples_path = semantic_style_examples_path()
    examples = _load_semantic_style_examples(examples_path)
    marker = semantic_style_legacy_migration_marker_path()
    if marker.exists():
        return examples
    examples = migrate_legacy_profiles_to_examples(
        examples,
        _load_profiles(semantic_style_profiles_path()),
        now=int(time.time()),
    )
    _write_semantic_style_examples(examples_path, examples)
    atomic_write_text(marker, '{"version":2,"source":"legacy_profiles"}')
    return examples


def _write_semantic_style_examples(path: Path, examples: list[SemanticStyleExample]) -> None:
    tmp = path.with_suffix(".jsonl.tmp")
    payload = "".join(
        json.dumps(example.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":")) + "\n"
        for example in examples
    )
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(path)


def _apply_legacy_rhythm_statistics(
    profiles: dict[tuple[int, int, str], SemanticStyleProfile], example: SemanticStyleExample
) -> None:
    """让 legacy_unknown 样本也能沉淀群节奏统计，但不写对白字段（无可靠作者来源）。

    legacy 样本没有可靠的 trigger/reply 作者 id，不能作为真人接话对白注入；
    但其 reply_text 仍能反映本群真实回复的长度/气泡/节奏分布，纯统计入 profile
    喂给 build_rhythm_baseline_note，不污染 direct_pairs/rewrite_seeds/matched_examples。
    """
    reply_text = _short_text(example.reply_text, _MAX_SEED_LEN)
    if not reply_text:
        return
    key = _profile_key(example.bot_id, example.group_id, example.scene)
    existing = profiles.get(key)
    bubble_count, segment_char_lengths, rhythm = deterministic_reply_shape(example.reply_text)
    if not bubble_count:
        return
    if existing is None:
        existing = SemanticStyleProfile(
            bot_id=example.bot_id,
            group_id=example.group_id,
            scene=example.scene,
            human_only=True,
            updated_at=example.created_at,
        )
        profiles[key] = existing
    existing.bubble_counts = [*existing.bubble_counts, bubble_count][-100:]
    existing.segment_char_lengths = [*existing.segment_char_lengths, *segment_char_lengths][-300:]
    existing.rhythm_counts[rhythm] = int(existing.rhythm_counts.get(rhythm) or 0) + 1
    existing.sample_count += 1
    existing.common_style_sample_count += 1


def _rebuild_profiles(
    examples: list[SemanticStyleExample], *, now: int
) -> dict[tuple[int, int, str], SemanticStyleProfile]:
    profiles: dict[tuple[int, int, str], SemanticStyleProfile] = {}
    for example in sorted(examples, key=lambda item: (item.created_at, item.example_id)):
        if example.source_kind == "legacy_unknown":
            _apply_legacy_rhythm_statistics(profiles, example)
            continue
        if example.source_kind != "human_pair":
            continue
        reply_is_bot = _example_reply_is_bot(example)
        if not reply_is_bot and not is_human_semantic_style_pair(
            trigger_user_id=example.trigger_user_id,
            reply_user_id=example.reply_user_id,
            bot_id=example.bot_id,
        ):
            continue
        key = _profile_key(example.bot_id, example.group_id, example.scene)
        profiles[key] = _build_profile(example, profiles.get(key), now=now, is_bot_reply=reply_is_bot)
    return profiles


def _example_reply_is_bot(example: SemanticStyleExample) -> bool:
    """判断某 example 的接话端是否为 bot（自身或协作 bot），用于 self_reflection 学习。"""
    from pallas.product.llm.sender_identity import sender_kind

    return sender_kind(example.reply_user_id, self_bot_id=example.bot_id) != "human"


def prune_semantic_style_examples(*, now: int | None = None) -> int:
    current_time = int(time.time()) if now is None else int(now)
    with semantic_style_data_lock():
        examples_path = semantic_style_examples_path()
        retained = [
            example
            for example in load_examples_with_legacy_migration_locked()
            if example.created_at >= current_time - SEMANTIC_STYLE_RETENTION_SEC
        ]
        _write_semantic_style_examples(examples_path, retained)
        _write_profiles(_rebuild_profiles(retained, now=current_time))
        return len(retained)


def cached_semantic_style_profile(bot_id: int, group_id: int | None, scene: str) -> SemanticStyleProfile | None:
    if group_id is None:
        return None
    key = _profile_key(bot_id, group_id, scene)
    with _profiles_lock:
        exact = _profiles.get(key)
        return exact.model_copy(deep=True) if exact is not None else None


def semantic_style_profile_summary(profile: SemanticStyleProfile | None) -> dict[str, Any] | None:
    if profile is None:
        return None
    bubble_counts = sorted(int(value) for value in profile.bubble_counts if int(value) > 0)
    segment_lengths = sorted(int(value) for value in profile.segment_char_lengths if int(value) > 0)
    rhythm_counts = {str(key): max(0, int(value)) for key, value in profile.rhythm_counts.items()}
    rhythm_total = sum(rhythm_counts.values())

    def percentile(values: list[int], fraction: float) -> int:
        return values[round((len(values) - 1) * fraction)] if values else 0

    return {
        "profile_ref": f"{profile.bot_id}:{profile.group_id}:{profile.scene}",
        "scene": profile.scene,
        "sample_count": profile.sample_count,
        "direct_example_count": len(profile.direct_examples),
        "direct_pair_count": len(profile.direct_pairs),
        "rewrite_seed_count": len(profile.rewrite_seeds),
        "intensity_counts": dict(profile.intensity_counts),
        "form_counts": dict(profile.form_counts),
        "bubble_count_p50": percentile(bubble_counts, 0.5),
        "bubble_count_p90": percentile(bubble_counts, 0.9),
        "segment_char_length_p50": percentile(segment_lengths, 0.5),
        "segment_char_length_p90": percentile(segment_lengths, 0.9),
        "rhythm_distribution": {key: round(value / rhythm_total, 4) for key, value in rhythm_counts.items()}
        if rhythm_total
        else {},
        "updated_at": profile.updated_at,
    }


def semantic_style_injection_enabled(
    request_id: str, *, bot_id: int | None = None, group_id: int | None = None
) -> bool:
    """只读注入位，保留稳定的 10% 对照组。"""
    if bot_id is not None and group_id is not None and (int(bot_id) <= 0 or int(group_id) <= 0):
        return False
    if not load_semantic_style_settings(bot_id=bot_id, group_id=group_id).injection_enabled:
        return False
    digest = hashlib.blake2b(str(request_id).encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") % 10 != 0


def semantic_style_collection_enabled(*, bot_id: int | None = None, group_id: int | None = None) -> bool:
    if bot_id is not None and group_id is not None and (int(bot_id) <= 0 or int(group_id) <= 0):
        return False
    return load_semantic_style_settings(bot_id=bot_id, group_id=group_id).collection_enabled


def semantic_style_source_example_id(pair: SemanticStyleDirectPair) -> str:
    source_id = str(pair.source_example_id or "").strip()
    if source_id:
        return source_id
    payload = f"{pair.trigger_text}\x00{pair.reply_text}".encode()
    return f"semantic:{hashlib.sha256(payload).hexdigest()}"


def filter_semantic_style_pairs_by_feedback(
    pairs: Iterable[SemanticStyleDirectPair], *, bot_id: int, group_id: int | None
) -> list[SemanticStyleDirectPair]:
    normalized = [
        pair.model_copy(update={"source_example_id": semantic_style_source_example_id(pair)}) for pair in pairs
    ]
    if group_id is None or int(group_id) <= 0:
        return normalized
    try:
        from pallas.product.llm.injection_feedback import effective_source_score

        return [
            pair
            for pair in normalized
            if effective_source_score(int(bot_id), int(group_id), "semantic", pair.source_example_id) > -4.0
        ]
    except Exception as exc:
        log_rate_limited(
            logger,
            "warning",
            "llm.injection_governance.semantic_filter_failed",
            "semantic injection governance filter failed for bot [{}] and group [{}]: [{}]",
            bot_id,
            group_id,
            exc,
        )
        return normalized


def resolve_cached_semantic_style(
    bot_id: int,
    group_id: int | None,
    scene: str,
    *,
    request_id: str,
    query_text: str = "",
    recent_assistant_replies: Iterable[str] = (),
    bypass_injection_gate: bool = False,
) -> SemanticStyleResolution:
    if not bypass_injection_gate and not semantic_style_injection_enabled(request_id, bot_id=bot_id, group_id=group_id):
        return SemanticStyleResolution()
    profile = cached_semantic_style_profile(bot_id, group_id, scene)
    if profile is None or not profile.human_only:
        return SemanticStyleResolution()
    direct_pairs = filter_semantic_style_pairs_by_feedback(profile.direct_pairs, bot_id=bot_id, group_id=group_id)
    rewrite_seed = profile.rewrite_seeds[-1] if profile.rewrite_seeds else ""
    if not rewrite_seed and profile.direct_examples:
        rewrite_seed = profile.direct_examples[-1]
    direct_pair = select_semantic_style_direct_pair(
        direct_pairs,
        query_text=query_text,
        recent_assistant_replies=recent_assistant_replies,
    )
    safe_matched = [
        pair
        for pair in select_semantic_style_matched_pairs(
            direct_pairs,
            query_text=query_text,
            recent_assistant_replies=recent_assistant_replies,
            limit=_MATCHED_EXAMPLE_LIMIT,
        )
        if prompt_safe_expression_sample(pair.trigger_text) and prompt_safe_expression_sample(pair.reply_text)
    ]
    matched_examples = [
        (_short_text(pair.trigger_text, _MAX_SEED_LEN), _short_text(pair.reply_text, _MAX_SEED_LEN))
        for pair in safe_matched
    ]
    safe_anchor = prompt_safe_expression_sample(profile.style_anchor)
    safe_seed = prompt_safe_expression_sample(rewrite_seed)
    safe_direct_candidate = prompt_safe_expression_sample(direct_pair.reply_text) if direct_pair is not None else ""
    behavior_strategies = (
        []
        if matched_examples
        else [
            strategy
            for strategy in select_behavior_strategies(profile.behavior_strategies, query_text=query_text)
            if prompt_safe_expression_sample(strategy.scene) and prompt_safe_expression_sample(strategy.action)
        ]
    )
    return SemanticStyleResolution(
        style_anchor=safe_anchor,
        prompt_block=append_cached_semantic_style_block("", safe_anchor, safe_seed),
        matched_examples=matched_examples,
        matched_example_sources=safe_matched,
        direct_candidate=safe_direct_candidate,
        source_example_id=semantic_style_source_example_id(direct_pair) if direct_pair is not None else "",
        baseline_note=build_rhythm_baseline_note(profile),
        behavior_strategies=behavior_strategies[:_BEHAVIOR_STRATEGY_MAX_HITS],
        style_profile=semantic_style_profile_summary(profile) or {},
    )


def prompt_safe_expression_sample(value: str) -> str:
    text = str(value or "").strip()
    if not text or len(text) > _MAX_SEED_LEN:
        return ""
    if any(unicodedata.category(character).startswith("C") for character in text):
        return ""
    normalized = unicodedata.normalize("NFKC", text).casefold()
    blocked = ("@", "http", "www.", "system", "developer", "ignore", "指令", "规则", "角色", "<|", "[inst]")
    if any(token in normalized for token in blocked):
        return ""
    if re.search(r"\d{7,}|\[cq:|qq(?:号)?\d|\brole\s*[:=]", normalized):
        return ""
    return _short_text(text, _MAX_SEED_LEN)


def normalize_semantic_style_match_text(value: str) -> str:
    return "".join(character.lower() for character in str(value or "") if character.isalnum())


def semantic_style_text_similarity(left: str, right: str) -> float:
    normalized_left = normalize_semantic_style_match_text(left)
    normalized_right = normalize_semantic_style_match_text(right)
    if not normalized_left or not normalized_right:
        return 0.0
    if normalized_left == normalized_right:
        return 1.0
    if min(len(normalized_left), len(normalized_right)) < 2:
        return 0.0
    left_pairs = {normalized_left[index : index + 2] for index in range(len(normalized_left) - 1)}
    right_pairs = {normalized_right[index : index + 2] for index in range(len(normalized_right) - 1)}
    return len(left_pairs & right_pairs) / min(len(left_pairs), len(right_pairs))


def select_semantic_style_direct_candidate(
    pairs: Iterable[SemanticStyleDirectPair],
    *,
    query_text: str,
    recent_assistant_replies: Iterable[str] = (),
) -> str:
    pair = select_semantic_style_direct_pair(
        pairs,
        query_text=query_text,
        recent_assistant_replies=recent_assistant_replies,
    )
    return _short_text(pair.reply_text, _MAX_SEED_LEN) if pair is not None else ""


def select_behavior_strategies(
    strategies: Iterable[BehaviorStrategy],
    *,
    query_text: str,
) -> list[BehaviorStrategy]:
    """按当前触发句对策略池打分召回，场景/动作相似且次数更高者优先。"""
    ranked = sorted(
        (
            (
                max(
                    semantic_style_text_similarity(query_text, strategy.trigger),
                    semantic_style_text_similarity(query_text, strategy.scene),
                ),
                index,
                strategy,
            )
            for index, strategy in enumerate(strategies)
            if strategy.scene and strategy.action
        ),
        reverse=True,
    )
    hits: list[BehaviorStrategy] = []
    for score, _index, strategy in ranked:
        if score < _BEHAVIOR_STRATEGY_MIN_SIMILARITY:
            break
        hits.append(strategy)
        if len(hits) >= _BEHAVIOR_STRATEGY_MAX_HITS:
            break
    return hits


def build_rhythm_baseline_note(profile: SemanticStyleProfile | None) -> str:
    """渲染一行本群真人接话节奏基线；样本不足时返回空串。"""
    if profile is None or profile.sample_count < _BASELINE_MIN_SAMPLE:
        return ""
    bubble_counts = sorted(int(value) for value in profile.bubble_counts if int(value) > 0)
    segment_lengths = sorted(int(value) for value in profile.segment_char_lengths if int(value) > 0)
    rhythm_counts = {str(key): max(0, int(value)) for key, value in profile.rhythm_counts.items()}
    rhythm_total = sum(rhythm_counts.values())
    if not bubble_counts or not segment_lengths or not rhythm_total:
        return ""
    single_ratio = round(int(rhythm_counts.get("single") or 0) / rhythm_total * 100)
    median_segment = segment_lengths[round((len(segment_lengths) - 1) * 0.5)]
    parts = [f"本群真人单条短气泡为主（占比约 {single_ratio}%），单段中位约 {median_segment} 字"]
    visual_ratio = round(profile.visual_sample_count / profile.sample_count * 100)
    if visual_ratio >= 5:
        parts.append(f"约 {visual_ratio}% 的回复带图")
    return "；".join(parts) + "。"


def select_semantic_style_matched_pairs(
    pairs: Iterable[SemanticStyleDirectPair],
    *,
    query_text: str,
    recent_assistant_replies: Iterable[str] = (),
    limit: int = _MATCHED_EXAMPLE_LIMIT,
) -> list[SemanticStyleDirectPair]:
    """按当前触发句相似度召回具体真人接话对，作为可见回复的参考示例。"""
    recent = [reply for reply in recent_assistant_replies if normalize_semantic_style_match_text(reply)]
    ranked = sorted(
        (
            (semantic_style_text_similarity(query_text, pair.trigger_text), index, pair)
            for index, pair in enumerate(pairs)
            if pair.trigger_text and pair.reply_text
        ),
        reverse=True,
    )
    hits: list[SemanticStyleDirectPair] = []
    for score, _index, pair in ranked:
        if score < _DIRECT_TRIGGER_SIMILARITY:
            break
        if any(
            semantic_style_text_similarity(pair.reply_text, previous) >= _DIRECT_REPLY_DEDUP_SIMILARITY
            for previous in recent
        ):
            continue
        hits.append(pair)
        if len(hits) >= max(1, min(2, int(limit))):
            break
    return hits


def select_semantic_style_direct_pair(
    pairs: Iterable[SemanticStyleDirectPair],
    *,
    query_text: str,
    recent_assistant_replies: Iterable[str] = (),
) -> SemanticStyleDirectPair | None:
    recent = [reply for reply in recent_assistant_replies if normalize_semantic_style_match_text(reply)]
    ranked = sorted(
        (
            (semantic_style_text_similarity(query_text, pair.trigger_text), index, pair)
            for index, pair in enumerate(pairs)
        ),
        reverse=True,
    )
    for score, _index, pair in ranked:
        if score < _DIRECT_TRIGGER_SIMILARITY:
            break
        if any(
            semantic_style_text_similarity(pair.reply_text, previous) >= _DIRECT_REPLY_DEDUP_SIMILARITY
            for previous in recent
        ):
            continue
        return pair
    return None


def should_deliver_semantic_style_direct_candidate(
    *, bot_id: int | None, group_id: int | None, candidate: str | None
) -> bool:
    """按群维护最近 100 次内核任务的直投占比。"""
    settings = load_semantic_style_settings(bot_id=bot_id, group_id=group_id)
    if not settings.injection_enabled or not settings.direct_enabled:
        return False
    key = (int(bot_id or 0), int(group_id or 0))
    text = _short_text(candidate, _MAX_SEED_LEN)
    with _profiles_lock:
        window = _direct_quota_windows.setdefault(key, deque(maxlen=_DIRECT_QUOTA_WINDOW))
        limit = 1 if len(window) < _DIRECT_QUOTA_WARMUP else int(_DIRECT_QUOTA_WINDOW * _DIRECT_QUOTA_RATE)
        approved = bool(text) and sum(window) < limit
        window.append(approved)
    return approved


def build_cached_semantic_style_block(bot_id: int, group_id: int | None, scene: str) -> str:
    profile = cached_semantic_style_profile(bot_id, group_id, scene)
    if profile is None:
        return ""
    rewrite_seed = profile.rewrite_seeds[-1] if profile.rewrite_seeds else ""
    if not rewrite_seed and profile.direct_examples:
        rewrite_seed = profile.direct_examples[-1]
    return append_cached_semantic_style_block("", profile.style_anchor, rewrite_seed)


def append_cached_semantic_style_block(system_prompt: str, style_anchor: str, rewrite_seed: str) -> str:
    parts = ["【本群表达校准】"]
    anchor = _short_text(style_anchor, _MAX_STYLE_ANCHOR_LEN)
    seed = _short_text(rewrite_seed, _MAX_SEED_LEN)
    if anchor:
        parts.append(f"保持：{anchor}")
    if seed:
        parts.append(f"可借鉴句式：{seed}")
    block = "\n".join(parts) if len(parts) > 1 else ""
    base = str(system_prompt or "").strip()
    return f"{base}\n\n{block}".strip() if base and block else (block or base)


def _parse_label_response(content: str) -> tuple[SemanticStyleLabel, BehaviorStrategy | None]:
    text = _JSON_FENCE_RE.sub("", str(content or "").strip()).strip()
    try:
        raw = json.loads(text)
    except json.JSONDecodeError:
        return parse_semantic_style_label({}), None
    if not isinstance(raw, dict):
        return parse_semantic_style_label({}), None
    return parse_semantic_style_label(raw), parse_behavior_strategy(raw.get("behavior_strategy"))


async def label_semantic_style_with_llm(
    *, trigger_text: str, reply_text: str, pair_relation: Literal["quoted", "adjacent"] = "adjacent"
) -> tuple[SemanticStyleLabel, BehaviorStrategy | None]:
    from pallas.product.llm.config import get_llm_config
    from pallas.product.llm.provider_client import complete_chat_message

    cfg = get_llm_config()
    prompt = (
        "分析真实群聊的候选「前句→接话」，只输出严格 JSON：is_reply_pair、transferable、"
        "interaction_actions、semantic_relations、intensity、forms、behavior_strategy。"
        "is_reply_pair 仅当前句确实在回应前句时为 true；transferable 仅接话脱离当时人名、"
        "多人局部梗或临时事实后仍可作为通用措辞参考时为 true。任一不成立都填 false。"
        "intensity 只能 quiet/soft/neutral/sharp/strong；"
        "数组字段用受控英文词。behavior_strategy 为 null 或 "
        '{"scene":"可泛化场景","action":"实际接话动作","outcome":"可观察变化",'
        '"learning_type":"observed"}。不抄原话，不带人名/临时梗，不做价值判断。\n'
        f"关联：{'明确引用前句' if pair_relation == 'quoted' else '仅时间相邻'}\n"
        f"前句：{_short_text(trigger_text, 96)}\n接话：{_short_text(reply_text, 96)}"
    )
    response = await complete_chat_message(
        [{"role": "user", "content": prompt}],
        model=str(cfg.llm_model or ""),
        options={"temperature": 0, "max_tokens": 160},
        cfg=cfg,
        task="repeater.semantic_style",
    )
    return _parse_label_response(str(response.get("content") or ""))


async def label_semantic_style_visual_with_cached_image(*, cq_code: str) -> SemanticStyleVisualLabel | None:
    """仅将已有缓存图片暂时送入视觉模型，标签落盘时不保留图片引用或二进制。"""
    from pallas.core.shared.utils.media_cache import get_image
    from pallas.product.llm.providers_store import resolve_endpoint_for_task

    image = await get_image(cq_code)
    if not image:
        return None
    endpoint = resolve_endpoint_for_task("repeater_semantic_style")
    if endpoint is None or "image" not in endpoint.capabilities:
        return None
    if not claim_semantic_label_budget():
        return None
    import base64

    from pallas.product.llm.provider_client import complete_chat_message
    from pallas.product.llm.vision_messages import openai_vision_user_content

    content = openai_vision_user_content(
        "只描述图片中的群聊表达信号。只输出 JSON，字段只能是 subject、action、tone、text；"
        "subject=person/animal/character/object/food/landscape/text/abstract/unknown；"
        "action=reaction/gesture/pose/motion/dialog/none/unknown；"
        "tone=playful/cute/sarcastic/angry/sad/surprised/neutral/unknown；"
        "text=present/absent/unreadable/unknown。",
        [f"data:image/jpeg;base64,{base64.b64encode(image).decode('ascii')}"],
    )
    response = await complete_chat_message(
        [{"role": "user", "content": content}],
        model=endpoint.model,
        options={
            "temperature": 0.1,
            "max_tokens": task_token_budget("repeater.semantic_style", operation="vision"),
        },
        base_url=endpoint.base_url,
        api_key=endpoint.api_key,
        request_method=endpoint.request_method,
        task="repeater.semantic_style",
        provider_id=str(endpoint.provider_id or ""),
    )
    try:
        raw = json.loads(_JSON_FENCE_RE.sub("", str(response.get("content") or "").strip()).strip())
    except json.JSONDecodeError:
        raw = {}
    return parse_semantic_style_visual_label(raw)


async def maybe_label_semantic_style_visual(payload: dict[str, Any]) -> SemanticStyleVisualLabel | None:
    global _semantic_style_visual_circuit
    cq_code = str(payload.get("image_cq_code") or "").strip()
    if not cq_code or str(payload.get("source") or "realtime") != "realtime":
        return None
    now = int(time.time())
    with _profiles_lock:
        decision = semantic_style_visual_circuit_decision(_semantic_style_visual_circuit, enabled=True, now=now)
    if decision.mode in {"disabled", "skip"}:
        return None
    try:
        label = await label_semantic_style_visual_with_cached_image(cq_code=cq_code)
    except Exception as exc:
        with _profiles_lock:
            _semantic_style_visual_circuit = record_semantic_style_visual_circuit_failure(
                _semantic_style_visual_circuit, now=now
            )
        logger.debug("repeater semantic style visual label skipped: {}", exc)
        return None
    with _profiles_lock:
        _semantic_style_visual_circuit = record_semantic_style_visual_circuit_success(
            _semantic_style_visual_circuit, now=now
        )
    return label


async def label_semantic_style_with_retry(
    *, trigger_text: str, reply_text: str, pair_relation: Literal["quoted", "adjacent"] = "adjacent"
) -> tuple[SemanticStyleLabel, BehaviorStrategy | None] | None:
    for retry_index in range(SEMANTIC_STYLE_LABEL_MAX_RETRIES + 1):
        if not claim_semantic_label_budget():
            return None
        try:
            return await label_semantic_style_with_llm(
                trigger_text=trigger_text,
                reply_text=reply_text,
                pair_relation=pair_relation,
            )
        except Exception as exc:
            if retry_index >= SEMANTIC_STYLE_LABEL_MAX_RETRIES:
                logger.warning("repeater semantic style label dropped after retries: {}", exc)
                return None
            logger.debug("Repeater semantic style label retry [{}] failed: [{}]", retry_index + 1, exc)
    return None


async def label_semantic_style_batch_with_llm(
    pairs: list[tuple[str, str, Literal["quoted", "adjacent"]]],
    *,
    max_batch: int = SEMANTIC_STYLE_LABEL_BATCH_MAX,
) -> list[tuple[SemanticStyleLabel, BehaviorStrategy | None] | None]:
    """一次 LLM 提交批量标注多个「前句→接话」对，逐项返回标签。

    参照 gsuid 后台管线的「一次输出 JSON 数组」范式，显著降低语义风格采集的
    LLM 提交次数。批量解析缺项时仅对缺失下标回退单对接口
    ``label_semantic_style_with_retry``，已解析项按位置保留。
    """
    from pallas.product.llm.config import get_llm_config
    from pallas.product.llm.provider_client import complete_chat_message

    results: list[tuple[SemanticStyleLabel, BehaviorStrategy | None] | None] = []
    remaining = list(pairs)
    while remaining:
        chunk = remaining[:max_batch]
        remaining = remaining[max_batch:]
        prompt_items = []
        for index, (trigger_text, reply_text, pair_relation) in enumerate(chunk):
            relation = "明确引用前句" if pair_relation == "quoted" else "仅时间相邻"
            prompt_items.append(
                f"[{index}] 关联：{relation}\n前：{_short_text(trigger_text, 72)}\n后：{_short_text(reply_text, 72)}"
            )
        cfg = get_llm_config()
        prompt = _label_semantic_style_batch_prompt(len(chunk)) + "\n\n" + "\n\n".join(prompt_items)
        if not claim_semantic_label_budget():
            return results
        try:
            response = await complete_chat_message(
                [{"role": "user", "content": prompt}],
                model=str(cfg.llm_model or ""),
                options={"temperature": 0, "max_tokens": 128 * len(chunk)},
                cfg=cfg,
                task="repeater.semantic_style",
            )
            parsed = _parse_label_batch_response(str(response.get("content") or ""), len(chunk))
        except Exception as exc:
            logger.warning("repeater semantic style batch label failed: {}", exc)
            parsed = []
        if len(parsed) == len(chunk):
            results.extend(parsed)
            continue
        # 批量解析不完整（缺项/异常）时，仅对缺失下标逐对回退单对标注；
        # 已解析出的项按位置直接保留，避免整批重标放大调用量。
        logger.debug(
            "Repeater semantic style batch incomplete ([{}]/[{}]); falling back for missing",
            len(parsed),
            len(chunk),
        )
        results.extend(parsed)
        for item in chunk[len(parsed) :]:
            fallback = await label_semantic_style_with_retry(
                trigger_text=item[0], reply_text=item[1], pair_relation=item[2]
            )
            results.append(fallback)
    return results


def _label_semantic_style_batch_prompt(count: int) -> str:
    return (
        f"判断 {count} 组群聊前后句，只输出长度为 {count} 的 JSON 数组。字段："
        "is_reply_pair、transferable、interaction_actions、semantic_relations、intensity、forms、behavior_strategy。"
        "确实回应前句才 is_reply_pair=true；脱离人名、局部梗、临时事实仍可复用才 transferable=true，"
        "否则均为 false。intensity 只能 quiet/soft/neutral/sharp/strong，数组字段只能用受控英文词。"
        "behavior_strategy 为 null 或 "
        '{"scene":"可泛化场景","action":"实际接话动作","outcome":"可观察变化",'
        '"learning_type":"observed"}。不抄原话，不带人名或临时梗。严格按输入顺序输出。'
    )


def _parse_label_batch_response(
    content: str,
    expected: int,
) -> list[tuple[SemanticStyleLabel, BehaviorStrategy | None]]:
    """解析批量标注响应为逐项 (label, strategy)；缺项或非法用空标签补齐到 len(响应)。"""
    text = _JSON_FENCE_RE.sub("", str(content or "").strip()).strip()
    try:
        raw = json.loads(text)
    except json.JSONDecodeError:
        return []
    if not isinstance(raw, list):
        return []
    results: list[tuple[SemanticStyleLabel, BehaviorStrategy | None]] = []
    for item in raw:
        if not isinstance(item, dict):
            results.append((SemanticStyleLabel(), None))
            continue
        label, strategy = parse_semantic_style_label(item), parse_behavior_strategy(item.get("behavior_strategy"))
        results.append((label, strategy))
    return results[:expected]


async def _refresh_loop() -> None:
    while True:
        await asyncio.sleep(_PROFILE_REFRESH_SEC)
        try:
            refresh_semantic_style_cache()
        except Exception:
            logger.debug("repeater semantic style cache refresh skipped")


def register_semantic_style_cache_startup_hook() -> None:
    global _startup_bound, _reload_task
    if _startup_bound:
        return
    _startup_bound = True
    driver = get_driver()

    @driver.on_startup
    async def _on_startup() -> None:
        global _reload_task
        refresh_semantic_style_cache(force=True)
        _reload_task = asyncio.create_task(_refresh_loop(), name="repeater_semantic_style_cache")
        register_startup_ready("语义风格缓存")

    @driver.on_shutdown
    async def _on_shutdown() -> None:
        global _reload_task
        if _reload_task is not None:
            _reload_task.cancel()
            await asyncio.gather(_reload_task, return_exceptions=True)
            _reload_task = None
