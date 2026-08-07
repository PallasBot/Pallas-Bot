"""后台标注复读语料，并向生成侧提供只读风格快照。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
from collections import Counter, deque
from pathlib import Path
from threading import RLock
from typing import TYPE_CHECKING, Any, Literal

from nonebot import get_bots, get_driver, logger
from pydantic import BaseModel, ConfigDict, Field

from pallas.core.foundation.db import make_local_context_repository, make_message_repository
from pallas.core.foundation.paths import plugin_data_dir
from pallas.core.platform.work_jobs.models import WorkJob
from pallas.core.platform.work_jobs.runtime import build_work_job_store

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

SEMANTIC_STYLE_LABEL_VERSION = 1
SEMANTIC_STYLE_RETENTION_SEC = 90 * 24 * 60 * 60
BOT_STYLE_RECENT_SEC = 14 * 24 * 60 * 60
BOT_STYLE_POSITIVE_REPLY_SEC = 90
BOT_STYLE_PROMOTION_SAMPLE_COUNT = 20
BOT_STYLE_PROMOTION_RECENT_SAMPLE_COUNT = 8
SEMANTIC_STYLE_BACKFILL_WINDOW_SEC = 30 * 24 * 60 * 60
SEMANTIC_STYLE_BACKFILL_JOB_TTL_SEC = 7 * 24 * 60 * 60
SEMANTIC_STYLE_BACKFILL_MAX_PER_DAY = 128
SEMANTIC_STYLE_LABEL_MAX_RETRIES = 2
_SEMANTIC_STYLE_BACKFILL_GROUP_LIMIT = 128
_SEMANTIC_STYLE_BACKFILL_PAGE_SIZE = 32
_SEMANTIC_STYLE_BACKFILL_START_DELAY_SEC = 30.0
_SEMANTIC_STYLE_BACKFILL_INTERVAL_SEC = 24 * 60 * 60

_REUSE_VALUES = {"direct", "rewrite", "style"}
_INTENSITY_VALUES = {"quiet", "soft", "neutral", "sharp", "strong"}
_OUTCOME_VALUES = {"engaged", "flat", "ignored", "conflict", "unknown"}
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
PERSONA_AFFINITY_VOCABULARY = frozenset({"calm", "chaotic", "concise", "deadpan", "mouthy", "playful", "warm"})
_MAX_LABEL_ITEMS = 8
_MAX_STYLE_ANCHOR_LEN = 80
_MAX_SEED_LEN = 80
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
    outcome: Literal["engaged", "flat", "ignored", "conflict", "unknown"] = "unknown"
    reuse: Literal["direct", "rewrite", "style"] = "style"
    persona_affinities: list[str] = Field(default_factory=list)
    style_anchor: str = ""
    visual: SemanticStyleVisualLabel | None = None


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
    bot_style_positive: bool = False


class SemanticStyleProfile(BaseModel):
    model_config = ConfigDict(extra="ignore")

    bot_id: int
    group_id: int
    scene: str
    style_anchor: str = ""
    direct_examples: list[str] = Field(default_factory=list)
    rewrite_seeds: list[str] = Field(default_factory=list)
    interaction_actions: list[str] = Field(default_factory=list)
    semantic_relations: list[str] = Field(default_factory=list)
    persona_affinities: list[str] = Field(default_factory=list)
    sample_count: int = 0
    common_style_sample_count: int = 0
    bot_style_sample_count: int = 0
    recent_bot_style_sample_count: int = 0
    bot_style_promoted: bool = False
    updated_at: int = 0


class SemanticStyleResolution(BaseModel):
    style_anchor: str = ""
    prompt_block: str = ""
    direct_candidate: str = ""


class SemanticStyleOverride(BaseModel):
    aggressive: bool = True
    nonsense: bool = True
    direct: bool = True
    image: bool = True


class SemanticStyleSettings(BaseModel):
    enabled: bool = True
    overrides: SemanticStyleOverride = Field(default_factory=SemanticStyleOverride)


class SemanticStyleBackfillCursor(BaseModel):
    """调用方持久化的历史页游标与当日已入队数量。"""

    before_created_at: int = 0
    before_message_id: int = 0
    day_started_at: int = 0
    enqueued_today: int = 0


class SemanticStyleBackfillBatch(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    jobs: list[WorkJob] = Field(default_factory=list)
    cursor: SemanticStyleBackfillCursor = Field(default_factory=SemanticStyleBackfillCursor)
    deferred: bool = False


_profiles_lock = RLock()
_profiles: dict[tuple[int, int, str], SemanticStyleProfile] = {}
_profiles_revision: tuple[int, int] | None = None
_reload_task: asyncio.Task[None] | None = None
_backfill_task: asyncio.Task[None] | None = None
_startup_bound = False
_direct_quota_windows: dict[tuple[int, int], deque[bool]] = {}
_semantic_style_visual_circuit = SemanticStyleVisualCircuitState()
_DIRECT_QUOTA_WINDOW = 100
_DIRECT_QUOTA_RATE = 0.15
_DIRECT_QUOTA_WARMUP = 20


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


async def collect_semantic_style_backfill_candidates(
    *,
    now: int | None = None,
    bot_ids: Iterable[int] | None = None,
    cursor: SemanticStyleBackfillCursor | None = None,
) -> list[dict[str, object]]:
    """从本机消息与已学习 Answer 交叉还原历史 bot 接话关系。"""
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
            logger.warning("repeater semantic style backfill list groups failed bot={}: {}", bot_id, exc)
            continue
        for group_id in group_ids:
            gid = int(group_id)
            if not semantic_style_collection_enabled(bot_id=bot_id, group_id=gid):
                continue
            try:
                answers = await list_answers(gid, cutoff)
            except Exception as exc:
                logger.warning("repeater semantic style backfill list answers failed group={}: {}", gid, exc)
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
                    logger.warning("repeater semantic style backfill list messages failed group={}: {}", gid, exc)
                    break
                ordered = list(messages)
                if not ordered:
                    break
                for index, reply_message in enumerate(ordered[1:], start=1):
                    predecessor = ordered[index - 1]
                    created_at = int(getattr(reply_message, "time", 0) or 0)
                    if created_at < cutoff:
                        continue
                    if int(getattr(reply_message, "user_id", 0) or 0) != bot_id:
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


async def run_semantic_style_backfill_round(*, now: int | None = None) -> int:
    """投递由 work aux 执行的每日历史扫描任务。"""
    current_time = int(time.time()) if now is None else int(now)
    bot_ids: list[int] = []
    for key, bot in get_bots().items():
        value = getattr(bot, "self_id", key)
        try:
            bot_id = int(value)
        except (TypeError, ValueError):
            continue
        if bot_id > 0 and bot_id not in bot_ids:
            bot_ids.append(bot_id)
    if not bot_ids:
        return 0
    day = current_time // (24 * 60 * 60)
    job = WorkJob.create(
        kind="repeater.semantic_style.backfill.scan",
        payload={"bot_ids": sorted(bot_ids), "now": current_time},
        idempotency_key=f"repeater.semantic_style.backfill.scan:{day}",
    )
    await build_work_job_store().enqueue(job)
    return 1


async def handle_repeater_semantic_style_backfill_scan(payload: dict[str, Any]) -> int:
    """在 work aux 扫描历史消息，并持久化生成的语义标注任务。"""
    current_time = int(payload.get("now") or time.time())
    bot_ids = [int(item) for item in payload.get("bot_ids", []) if int(item) > 0]
    if not bot_ids:
        return 0
    cursor = load_semantic_style_backfill_cursor()
    candidates = await collect_semantic_style_backfill_candidates(
        now=current_time,
        bot_ids=bot_ids,
        cursor=cursor,
    )
    batch = build_semantic_style_backfill_batch(
        candidates,
        cursor=cursor,
        now=current_time,
    )
    if not batch.jobs:
        return 0
    await build_work_job_store().enqueue_many(batch.jobs)
    save_semantic_style_backfill_cursor(batch.cursor)
    return len(batch.jobs)


def parse_semantic_style_label(value: object) -> SemanticStyleLabel:
    raw = value if isinstance(value, dict) else {}
    reuse = str(raw.get("reuse") or "").strip().lower()
    intensity = str(raw.get("intensity") or "").strip().lower()
    outcome = str(raw.get("outcome") or "").strip().lower()
    return SemanticStyleLabel(
        interaction_actions=_items(raw.get("interaction_actions"), INTERACTION_ACTION_VOCABULARY),
        semantic_relations=_items(raw.get("semantic_relations"), SEMANTIC_RELATION_VOCABULARY),
        intensity=intensity if intensity in _INTENSITY_VALUES else "neutral",
        forms=_items(raw.get("forms"), FORM_VOCABULARY),
        outcome=outcome if outcome in _OUTCOME_VALUES else "unknown",
        reuse=reuse if reuse in _REUSE_VALUES else "style",
        persona_affinities=_items(raw.get("persona_affinities"), PERSONA_AFFINITY_VOCABULARY),
        style_anchor=_short_text(raw.get("style_anchor"), _MAX_STYLE_ANCHOR_LEN),
        visual=parse_semantic_style_visual_label(raw.get("visual")) if isinstance(raw.get("visual"), dict) else None,
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
        "overrides": settings.overrides.model_dump(mode="json"),
        "example_count": len(scoped_examples),
        "profile_count": len(scoped_profiles),
        "backfill_cursor": load_semantic_style_backfill_cursor(bot_id=bot_id, group_id=group_id).model_dump(
            mode="json"
        ),
    }


def update_semantic_style_overrides(
    overrides: Mapping[str, object], *, bot_id: int | None = None, group_id: int | None = None
) -> dict[str, Any]:
    settings = load_semantic_style_settings(bot_id=bot_id, group_id=group_id)
    updated = settings.model_copy(
        update={
            "overrides": SemanticStyleOverride.model_validate({**settings.overrides.model_dump(), **dict(overrides)})
        }
    )
    _save_semantic_style_settings(updated, bot_id=bot_id, group_id=group_id)
    return semantic_style_status(bot_id=bot_id, group_id=group_id)


def set_semantic_style_enabled(
    enabled: bool, *, bot_id: int | None = None, group_id: int | None = None
) -> dict[str, Any]:
    settings = load_semantic_style_settings(bot_id=bot_id, group_id=group_id).model_copy(
        update={"enabled": bool(enabled)}
    )
    _save_semantic_style_settings(settings, bot_id=bot_id, group_id=group_id)
    return semantic_style_status(bot_id=bot_id, group_id=group_id)


def clear_semantic_style_data(*, bot_id: int | None = None, group_id: int | None = None) -> dict[str, Any]:
    scope = _semantic_style_scope(bot_id, group_id)
    examples = _load_semantic_style_examples(semantic_style_examples_path())
    retained = [example for example in examples if not _in_semantic_style_scope(example, scope)] if scope else []
    _write_semantic_style_examples(semantic_style_examples_path(), retained)
    _write_profiles(_rebuild_profiles(retained, now=int(time.time())))
    save_semantic_style_backfill_cursor(SemanticStyleBackfillCursor(), bot_id=bot_id, group_id=group_id)
    return semantic_style_status(bot_id=bot_id, group_id=group_id)


def rebuild_semantic_style_profiles(*, bot_id: int | None = None, group_id: int | None = None) -> dict[str, Any]:
    scope = _semantic_style_scope(bot_id, group_id)
    examples = _load_semantic_style_examples(semantic_style_examples_path())
    if scope is None:
        profiles = _rebuild_profiles(examples, now=int(time.time()))
    else:
        existing = _load_profiles(semantic_style_profiles_path())
        profiles = {key: profile for key, profile in existing.items() if not _in_semantic_style_scope(profile, scope)}
        profiles.update(
            _rebuild_profiles(
                [example for example in examples if _in_semantic_style_scope(example, scope)], now=int(time.time())
            )
        )
    _write_profiles(profiles)
    return semantic_style_status(bot_id=bot_id, group_id=group_id)


def semantic_style_quality(*, bot_id: int | None = None, group_id: int | None = None) -> dict[str, Any]:
    scope = _semantic_style_scope(bot_id, group_id)
    examples = _load_semantic_style_examples(semantic_style_examples_path())
    scoped_examples = [example for example in examples if _in_semantic_style_scope(example, scope)]
    return {
        **semantic_style_status(bot_id=bot_id, group_id=group_id),
        "label_version": SEMANTIC_STYLE_LABEL_VERSION,
        "reuse_counts": dict(Counter(example.label.reuse for example in scoped_examples)),
        "outcome_counts": dict(Counter(example.label.outcome for example in scoped_examples)),
        "positive_bot_style_count": sum(example.bot_style_positive for example in scoped_examples),
    }


def recover_semantic_style_data(*, bot_id: int | None = None, group_id: int | None = None) -> dict[str, Any]:
    rebuild_semantic_style_profiles(bot_id=bot_id, group_id=group_id)
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


def _build_profile(
    example: SemanticStyleExample,
    existing: SemanticStyleProfile | None,
    *,
    now: int | None = None,
) -> SemanticStyleProfile:
    label = example.label
    prior_actions = list(existing.interaction_actions) if existing else []
    prior_relations = list(existing.semantic_relations) if existing else []
    prior_affinities = list(existing.persona_affinities) if existing else []
    direct_examples = list(existing.direct_examples) if existing else []
    rewrite_seeds = list(existing.rewrite_seeds) if existing else []
    reply_text = _short_text(example.reply_text, _MAX_SEED_LEN)
    if label.reuse == "direct" and reply_text:
        direct_examples = [item for item in direct_examples if item != reply_text]
        direct_examples.append(reply_text)
    elif label.reuse == "rewrite" and reply_text:
        rewrite_seeds = [item for item in rewrite_seeds if item != reply_text]
        rewrite_seeds.append(reply_text)
    bot_style_sample_count = (existing.bot_style_sample_count if existing else 0) + int(example.bot_style_positive)
    recent_bot_style_sample_count = (existing.recent_bot_style_sample_count if existing else 0) + int(
        example.bot_style_positive and (now is None or example.created_at >= now - BOT_STYLE_RECENT_SEC)
    )
    return SemanticStyleProfile(
        bot_id=example.bot_id,
        group_id=example.group_id,
        scene=example.scene,
        style_anchor=label.style_anchor or (existing.style_anchor if existing else ""),
        direct_examples=direct_examples[-3:],
        rewrite_seeds=rewrite_seeds[-3:],
        interaction_actions=_popular([*prior_actions, *label.interaction_actions]),
        semantic_relations=_popular([*prior_relations, *label.semantic_relations]),
        persona_affinities=_popular([*prior_affinities, *label.persona_affinities]),
        sample_count=(existing.sample_count if existing else 0) + 1,
        common_style_sample_count=(existing.common_style_sample_count if existing else 0)
        + int(not example.bot_style_positive),
        bot_style_sample_count=bot_style_sample_count,
        recent_bot_style_sample_count=recent_bot_style_sample_count,
        bot_style_promoted=(
            bot_style_sample_count >= BOT_STYLE_PROMOTION_SAMPLE_COUNT
            and recent_bot_style_sample_count >= BOT_STYLE_PROMOTION_RECENT_SAMPLE_COUNT
        ),
        updated_at=example.created_at,
    )


def persist_semantic_style_example(example: SemanticStyleExample) -> SemanticStyleProfile:
    examples_path = semantic_style_examples_path()
    with examples_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(example.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":")) + "\n")
    profiles_path = semantic_style_profiles_path()
    profiles = _load_profiles(profiles_path)
    key = _profile_key(example.bot_id, example.group_id, example.scene)
    profile = _build_profile(example, profiles.get(key), now=int(time.time()))
    profiles[key] = profile
    _write_profiles(profiles)
    return profile


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
    following_created_at: int,
    following_is_bot: bool,
    following_text: str,
    following_is_banned: bool = False,
    following_has_negative_feedback: bool = False,
) -> SemanticStyleProfile | None:
    if not is_positive_bot_style_outcome(
        reply_created_at=example.created_at,
        following_created_at=following_created_at,
        following_is_bot=following_is_bot,
        following_text=following_text,
        following_is_banned=following_is_banned,
        following_has_negative_feedback=following_has_negative_feedback,
    ):
        return None
    positive_example = example.model_copy(update={"bot_style_positive": True})
    examples_path = semantic_style_examples_path()
    updated_examples: list[SemanticStyleExample] = []
    found = False
    for stored_example in _load_semantic_style_examples(examples_path):
        if stored_example.example_id != positive_example.example_id:
            updated_examples.append(stored_example)
            continue
        if not found:
            updated_examples.append(positive_example)
            found = True
    if not found:
        updated_examples.append(positive_example)
    _write_semantic_style_examples(examples_path, updated_examples)
    examples = updated_examples
    profiles = _rebuild_profiles(examples, now=max(item.created_at for item in examples))
    _write_profiles(profiles)
    return profiles.get(_profile_key(positive_example.bot_id, positive_example.group_id, positive_example.scene))


def _load_semantic_style_examples(path: Path) -> list[SemanticStyleExample]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    examples: list[SemanticStyleExample] = []
    for line in lines:
        try:
            raw = json.loads(line)
            example = SemanticStyleExample.model_validate(raw)
        except (json.JSONDecodeError, ValueError, TypeError):
            continue
        examples.append(example.model_copy(update={"label": parse_semantic_style_label(example.label.model_dump())}))
    return examples


def _write_semantic_style_examples(path: Path, examples: list[SemanticStyleExample]) -> None:
    tmp = path.with_suffix(".jsonl.tmp")
    payload = "".join(
        json.dumps(example.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":")) + "\n"
        for example in examples
    )
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(path)


def _rebuild_profiles(
    examples: list[SemanticStyleExample], *, now: int
) -> dict[tuple[int, int, str], SemanticStyleProfile]:
    profiles: dict[tuple[int, int, str], SemanticStyleProfile] = {}
    for example in sorted(examples, key=lambda item: (item.created_at, item.example_id)):
        key = _profile_key(example.bot_id, example.group_id, example.scene)
        profiles[key] = _build_profile(example, profiles.get(key), now=now)
    return profiles


def prune_semantic_style_examples(*, now: int | None = None) -> int:
    current_time = int(time.time()) if now is None else int(now)
    examples_path = semantic_style_examples_path()
    retained = [
        example
        for example in _load_semantic_style_examples(examples_path)
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


def semantic_style_injection_enabled(
    request_id: str, *, bot_id: int | None = None, group_id: int | None = None
) -> bool:
    """保留稳定的 10% 对照组。"""
    if not semantic_style_collection_enabled(bot_id=bot_id, group_id=group_id):
        return False
    digest = hashlib.blake2b(str(request_id).encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") % 10 != 0


def semantic_style_collection_enabled(*, bot_id: int | None = None, group_id: int | None = None) -> bool:
    if bot_id is not None and group_id is not None and (int(bot_id) <= 0 or int(group_id) <= 0):
        return False
    return load_semantic_style_settings(bot_id=bot_id, group_id=group_id).enabled


def resolve_cached_semantic_style(
    bot_id: int,
    group_id: int | None,
    scene: str,
    *,
    request_id: str,
) -> SemanticStyleResolution:
    if not semantic_style_injection_enabled(request_id, bot_id=bot_id, group_id=group_id):
        return SemanticStyleResolution()
    profile = cached_semantic_style_profile(bot_id, group_id, scene)
    if profile is None:
        return SemanticStyleResolution()
    rewrite_seed = profile.rewrite_seeds[-1] if profile.rewrite_seeds else ""
    if not rewrite_seed and profile.direct_examples:
        rewrite_seed = profile.direct_examples[-1]
    return SemanticStyleResolution(
        style_anchor=_short_text(profile.style_anchor, _MAX_STYLE_ANCHOR_LEN),
        prompt_block=append_cached_semantic_style_block("", profile.style_anchor, rewrite_seed),
        direct_candidate=_short_text(profile.direct_examples[-1] if profile.direct_examples else "", _MAX_SEED_LEN),
    )


def should_deliver_semantic_style_direct_candidate(
    *, bot_id: int | None, group_id: int | None, candidate: str | None
) -> bool:
    """按群维护最近 100 次内核任务的直投占比。"""
    settings = load_semantic_style_settings(bot_id=bot_id, group_id=group_id)
    if not settings.enabled or not settings.overrides.direct:
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


def _parse_label_response(content: str) -> SemanticStyleLabel:
    text = _JSON_FENCE_RE.sub("", str(content or "").strip()).strip()
    try:
        raw = json.loads(text)
    except json.JSONDecodeError:
        return parse_semantic_style_label({})
    return parse_semantic_style_label(raw)


async def label_semantic_style_with_llm(*, trigger_text: str, reply_text: str) -> SemanticStyleLabel:
    from pallas.product.llm.config import get_llm_config
    from pallas.product.llm.provider_client import complete_chat_message

    cfg = get_llm_config()
    prompt = (
        "分析一组真实群聊接话，输出严格 JSON。保留无意义附和、攻击性和胡话等表达特征，"
        "不要做价值判断。字段：interaction_actions、semantic_relations、intensity、forms、outcome、"
        "reuse、persona_affinities、style_anchor。reuse 只能 direct/rewrite/style；"
        "intensity 只能 quiet/soft/neutral/sharp/strong；outcome 只能 engaged/flat/ignored/conflict/unknown。"
        "style_anchor 用一句不超过 30 字的中文写法提示。\n"
        f"前句：{_short_text(trigger_text, 160)}\n接话：{_short_text(reply_text, 160)}"
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
        options={"temperature": 0.1, "max_tokens": 100},
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


async def label_semantic_style_with_retry(*, trigger_text: str, reply_text: str) -> SemanticStyleLabel | None:
    for retry_index in range(SEMANTIC_STYLE_LABEL_MAX_RETRIES + 1):
        try:
            return await label_semantic_style_with_llm(trigger_text=trigger_text, reply_text=reply_text)
        except Exception as exc:
            if retry_index >= SEMANTIC_STYLE_LABEL_MAX_RETRIES:
                logger.warning("repeater semantic style label dropped after retries: {}", exc)
                return None
            logger.debug("repeater semantic style label retry={} failed: {}", retry_index + 1, exc)
    return None


async def handle_repeater_semantic_style(payload: dict[str, Any]) -> None:
    if not semantic_style_collection_enabled(
        bot_id=int(payload.get("bot_id") or 0), group_id=int(payload.get("group_id") or 0)
    ):
        return
    trigger = str(payload.get("trigger_text") or "").strip()
    reply = str(payload.get("reply_text") or "").strip()
    if not trigger or not reply:
        return
    label = await label_semantic_style_with_llm(trigger_text=trigger, reply_text=reply)
    visual = await maybe_label_semantic_style_visual(payload)
    if visual is not None:
        label = label.model_copy(update={"visual": visual})
    example = SemanticStyleExample(
        example_id=str(payload.get("example_id") or f"{payload.get('group_id')}:{payload.get('message_id')}"),
        created_at=int(payload.get("created_at") or time.time()),
        bot_id=int(payload["bot_id"]),
        group_id=int(payload["group_id"]),
        scene=str(payload.get("scene") or "default"),
        trigger_text=_short_text(trigger, 240),
        reply_text=_short_text(reply, 240),
        label=label,
    )
    persist_semantic_style_example(example)


async def handle_repeater_semantic_style_visual(payload: dict[str, Any]) -> None:
    """兼容独立视觉 work job；语义关系仍由同一实时处理器持久化。"""
    await handle_repeater_semantic_style(payload)


async def handle_repeater_semantic_style_backfill(payload: dict[str, Any], *, now: int | None = None) -> None:
    """处理有限期历史标注；失败在本次任务内最多重试两次。"""
    if not semantic_style_collection_enabled(
        bot_id=int(payload.get("bot_id") or 0), group_id=int(payload.get("group_id") or 0)
    ):
        return
    current_time = int(time.time()) if now is None else int(now)
    if int(payload.get("expires_at") or 0) <= current_time:
        return
    trigger = str(payload.get("trigger_text") or "").strip()
    reply = str(payload.get("reply_text") or "").strip()
    if not trigger or not reply:
        return
    label = await label_semantic_style_with_retry(trigger_text=trigger, reply_text=reply)
    if label is None:
        return
    example = SemanticStyleExample(
        example_id=str(payload.get("example_id") or f"{payload.get('group_id')}:{payload.get('message_id')}"),
        created_at=int(payload.get("created_at") or current_time),
        bot_id=int(payload["bot_id"]),
        group_id=int(payload["group_id"]),
        scene=str(payload.get("scene") or "default"),
        trigger_text=_short_text(trigger, 240),
        reply_text=_short_text(reply, 240),
        label=label,
    )
    persist_semantic_style_example(example)


async def _refresh_loop() -> None:
    while True:
        await asyncio.sleep(_PROFILE_REFRESH_SEC)
        try:
            refresh_semantic_style_cache()
        except Exception:
            logger.debug("repeater semantic style cache refresh skipped")


def register_semantic_style_cache_startup_hook() -> None:
    global _startup_bound, _reload_task, _backfill_task
    if _startup_bound:
        return
    _startup_bound = True
    driver = get_driver()

    @driver.on_startup
    async def _on_startup() -> None:
        global _reload_task, _backfill_task
        refresh_semantic_style_cache(force=True)
        _reload_task = asyncio.create_task(_refresh_loop(), name="repeater_semantic_style_cache")

        async def _backfill_loop() -> None:
            await asyncio.sleep(_SEMANTIC_STYLE_BACKFILL_START_DELAY_SEC)
            while True:
                try:
                    await run_semantic_style_backfill_round()
                except Exception as exc:
                    logger.warning("repeater semantic style backfill round failed: {}", exc)
                await asyncio.sleep(_SEMANTIC_STYLE_BACKFILL_INTERVAL_SEC)

        _backfill_task = asyncio.create_task(_backfill_loop(), name="repeater_semantic_style_backfill")

    @driver.on_shutdown
    async def _on_shutdown() -> None:
        global _reload_task, _backfill_task
        if _reload_task is not None:
            _reload_task.cancel()
            await asyncio.gather(_reload_task, return_exceptions=True)
            _reload_task = None
        if _backfill_task is not None:
            _backfill_task.cancel()
            await asyncio.gather(_backfill_task, return_exceptions=True)
            _backfill_task = None
