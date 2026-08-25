"""Soft feedback primitives for llm_chat -> repeater."""

from __future__ import annotations

import asyncio
import json
import os
import re
import threading
import time
from collections import deque
from pathlib import Path
from threading import RLock
from typing import TYPE_CHECKING, Any

from nonebot import logger
from pydantic import BaseModel, ConfigDict, Field

from pallas.core.foundation.logging import log_rate_limited
from pallas.core.foundation.paths import plugin_data_dir
from pallas.core.platform.ai_callback.task_types import LLM_CHAT_TASK_TYPE
from pallas.product.llm.injection_feedback import InjectionSnapshot, NegativeOutcomeApplyResult
from pallas.product.llm.kernel.memory_governance import (
    can_collect_feedback,
)

if TYPE_CHECKING:
    from collections.abc import Callable

_BLOCKED_SOURCE_TAGS = {"memory", "relationship", "tool", "knowledge"}
_MAX_REPLY_LEN = 32
_MAX_PLAIN_CHAT_FEEDBACK_LEN = 120
_MAX_CORRECTION_LEN = 120
_TOP_REPLIES_LIMIT = 3
_TOP_SCENES_LIMIT = 5
_RECENT_WINDOW_MULTIPLIER = 4

_SYSTEM_PROMOTE_BLOCK_RE = re.compile(
    r"(欢迎(?:新人|进群|老师|加入)|进群欢迎|发言管理规则|警告一次|群公告|"
    r"投食成功|管理/开关|/bilibanshi|本群未开启|"
    r"亚托莉|思考中|（发呆）|\(发呆\))"
)

_FEEDBACK_TASK_TYPES = frozenset({LLM_CHAT_TASK_TYPE})


class LlmRepeaterFeedbackEntry(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    entry_id: str
    created_at: int
    bot_id: int
    group_id: int
    user_id: int
    request_id: str
    user_text: str
    reply_text: str
    behavior_scene: str = ""
    scene_tier: str = ""
    behavior_actions: list[str] = Field(default_factory=list)
    llm_route: str = ""
    source_tags: list[str] = Field(default_factory=list)
    eligible_for_bias: bool = True
    corrected_reply_text: str = ""
    corrected_at: int = 0
    bot_message_id: int = 0
    semantic_source_example_id: str = ""
    semantic_scene: str = ""
    injection_snapshot: InjectionSnapshot = Field(default_factory=InjectionSnapshot)


_GROUP_ENTRIES_CACHE_TTL_SEC = 5.0
_GROUP_ENTRIES_CACHE_MAX = 512
# (path, group_id, limit) -> (expire_monotonic, group_revision, rows)
_group_entries_cache: dict[tuple[str, int, int], tuple[float, int, list[LlmRepeaterFeedbackEntry]]] = {}
_group_entries_index_lock = RLock()
_group_entries_index_path = ""
_group_entries_index_revision: tuple[int, int] | None = None
_group_entries_index: dict[int, list[LlmRepeaterFeedbackEntry]] = {}
_group_entries_revisions: dict[int, int] = {}
_bot_message_index_path = ""
_bot_message_index_revision: tuple[int, int] | None = None
_bot_message_index: dict[tuple[int, int, int], LlmRepeaterFeedbackEntry] = {}
_feedback_index_prewarm_started = False


def clear_group_feedback_entries_cache() -> None:
    global \
        _bot_message_index, \
        _bot_message_index_path, \
        _bot_message_index_revision, \
        _group_entries_index, \
        _group_entries_index_path, \
        _group_entries_index_revision
    with _group_entries_index_lock:
        _group_entries_cache.clear()
        _group_entries_index_path = ""
        _group_entries_index_revision = None
        _group_entries_index = {}
        _group_entries_revisions.clear()
        _bot_message_index_path = ""
        _bot_message_index_revision = None
        _bot_message_index = {}


def schedule_feedback_index_prewarm() -> None:
    """后台预建 feedback 群索引，避免冷启动首条消息在事件循环里全量构建。

    构建期间与 on-demand 加锁互斥；结果天然被 revision 校验复用。
    """
    global _feedback_index_prewarm_started
    with _group_entries_index_lock:
        if _feedback_index_prewarm_started:
            return
        _feedback_index_prewarm_started = True

    def _run() -> None:
        try:
            path = feedback_base_dir(create=False) / "entries.jsonl"
            if path.exists():
                _group_entries_index_rows(path, group_id=0)
        except Exception as exc:  # noqa: BLE001
            logger.debug("feedback group index prewarm failed: {}", exc)

    threading.Thread(target=_run, name="feedback-group-index-prewarm", daemon=True).start()


def feedback_base_dir(*, create: bool = True) -> Path:
    env_dir = str(os.environ.get("PALLAS_DATA_DIR") or "").strip()
    if env_dir:
        root = Path(env_dir)
        if create:
            root.mkdir(parents=True, exist_ok=True)
        path = root / "llm_repeater_feedback"
        if create:
            path.mkdir(parents=True, exist_ok=True)
        return path
    path = plugin_data_dir("pb_webui", create=create) / "llm_repeater_feedback"
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def feedback_entries_path() -> Path:
    return feedback_base_dir() / "entries.jsonl"


def _feedback_entries_path_key(path: Path) -> str:
    try:
        return str(path.resolve())
    except OSError:
        return str(path)


def _feedback_entries_revision(path: Path) -> tuple[int, int]:
    try:
        stat = path.stat()
    except OSError:
        return (0, 0)
    return (int(stat.st_mtime_ns), int(stat.st_size))


def _group_entries_index_rows(path: Path, *, group_id: int) -> tuple[str, int, list[LlmRepeaterFeedbackEntry]]:
    global _group_entries_index_path, _group_entries_index_revision, _group_entries_index
    path_key = _feedback_entries_path_key(path)
    revision = _feedback_entries_revision(path)
    target_group_id = int(group_id)
    with _group_entries_index_lock:
        if _group_entries_index_path != path_key or _group_entries_index_revision != revision:
            rows_by_group: dict[int, list[LlmRepeaterFeedbackEntry]] = {}
            if path.exists():
                for item in _iter_feedback_entries(path):
                    rows_by_group.setdefault(int(item.group_id), []).append(item)
            _group_entries_index_path = path_key
            _group_entries_index_revision = _feedback_entries_revision(path)
            _group_entries_index = rows_by_group
            _group_entries_revisions.clear()
            _group_entries_cache.clear()
        return (
            path_key,
            _group_entries_revisions.get(target_group_id, 0),
            list(_group_entries_index.get(target_group_id, [])),
        )


def _note_feedback_entry_append(
    path: Path,
    entry: LlmRepeaterFeedbackEntry,
    *,
    before_revision: tuple[int, int],
    after_revision: tuple[int, int],
) -> None:
    global _bot_message_index_revision, _group_entries_index, _group_entries_index_path, _group_entries_index_revision
    path_key = _feedback_entries_path_key(path)
    group_id = int(entry.group_id)
    with _group_entries_index_lock:
        if _bot_message_index_path == path_key and _bot_message_index_revision == before_revision:
            if entry.bot_message_id > 0:
                _bot_message_index[(entry.bot_id, entry.group_id, entry.bot_message_id)] = entry
            _bot_message_index_revision = after_revision
        if _group_entries_index_path != path_key:
            return
        if _group_entries_index_revision != before_revision:
            _group_entries_cache.clear()
            _group_entries_index_path = ""
            _group_entries_index_revision = None
            _group_entries_index = {}
            _group_entries_revisions.clear()
            return
        _group_entries_index.setdefault(group_id, []).append(entry)
        _group_entries_index_revision = after_revision
        _group_entries_revisions[group_id] = _group_entries_revisions.get(group_id, 0) + 1


def normalize_feedback_llm_route(llm_route: str = "") -> str:
    return str(llm_route or "").strip()


def is_feedback_task_type(task_type: str) -> bool:
    return str(task_type or "").strip().lower() in _FEEDBACK_TASK_TYPES


def feedback_reply_max_len(*, task_type: str = "", llm_route: str = "") -> int:
    """corpus 短接话保持 32；plain 闲聊可更长以便反哺观测。"""
    route = str(llm_route or "").strip().lower()
    task = str(task_type or "").strip().lower()
    if route.startswith("plain_") or task == LLM_CHAT_TASK_TYPE:
        return _MAX_PLAIN_CHAT_FEEDBACK_LEN
    return _MAX_REPLY_LEN


def is_systemish_promote_text(*texts: str) -> bool:
    """欢迎/警告/管理句等不应进入自动晋升写回。"""
    for raw in texts:
        plain = str(raw or "").strip()
        if plain and _SYSTEM_PROMOTE_BLOCK_RE.search(plain):
            return True
    return False


def should_collect_llm_repeater_feedback(
    *,
    task_type: str,
    group_id: int | None,
    user_text: str,
    reply_text: str,
    source_tags: list[str],
    llm_route: str = "",
) -> bool:
    normalized_task = str(task_type or "").strip().lower()
    if normalized_task not in _FEEDBACK_TASK_TYPES:
        return False
    if int(group_id or 0) <= 0:
        return False
    trigger_text = str(user_text or "").strip()
    if not trigger_text:
        return False
    plain_reply = str(reply_text or "").strip()
    max_len = feedback_reply_max_len(task_type=normalized_task, llm_route=llm_route)
    if not plain_reply or len(plain_reply) > max_len:
        return False
    normalized_tags = {str(tag).strip().lower() for tag in source_tags if str(tag).strip()}
    if normalized_tags & _BLOCKED_SOURCE_TAGS:
        return False
    from pallas.product.llm.corpus_contamination import is_feedback_reply_collectable

    return is_feedback_reply_collectable(plain_reply)


def build_feedback_entry(**kwargs: Any) -> LlmRepeaterFeedbackEntry:
    return LlmRepeaterFeedbackEntry(
        entry_id=str(kwargs.get("entry_id") or kwargs["request_id"]).strip(),
        created_at=int(kwargs.get("created_at") or time.time()),
        bot_id=int(kwargs["bot_id"]),
        group_id=int(kwargs["group_id"]),
        user_id=int(kwargs["user_id"]),
        request_id=str(kwargs["request_id"]).strip(),
        user_text=str(kwargs.get("user_text") or "").strip(),
        reply_text=str(kwargs.get("reply_text") or "").strip(),
        behavior_scene=str(kwargs.get("behavior_scene") or "").strip(),
        scene_tier=str(kwargs.get("scene_tier") or "").strip(),
        behavior_actions=[
            str(item).strip() for item in list(kwargs.get("behavior_actions") or []) if str(item).strip()
        ],
        llm_route=str(kwargs.get("llm_route") or "").strip(),
        source_tags=[str(item).strip() for item in list(kwargs.get("source_tags") or []) if str(item).strip()],
        eligible_for_bias=bool(kwargs.get("eligible_for_bias", True)),
        corrected_reply_text=str(kwargs.get("corrected_reply_text") or "").strip(),
        corrected_at=int(kwargs.get("corrected_at") or 0),
        bot_message_id=int(kwargs.get("bot_message_id") or 0),
        semantic_source_example_id=str(kwargs.get("semantic_source_example_id") or "").strip(),
        semantic_scene=str(kwargs.get("semantic_scene") or "").strip(),
        injection_snapshot=InjectionSnapshot.model_validate(kwargs.get("injection_snapshot") or {}),
    )


def append_feedback_entry(entry: LlmRepeaterFeedbackEntry) -> None:
    from pallas.core.foundation.fs_lock import interprocess_file_lock

    path = feedback_entries_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(entry.model_dump(mode="json"), ensure_ascii=False) + "\n"
    with interprocess_file_lock(path.with_suffix(path.suffix + ".lock")):
        before_revision = _feedback_entries_revision(path)
        needs_leading_newline = False
        if path.exists() and path.stat().st_size > 0:
            with path.open("rb") as existing:
                existing.seek(-1, os.SEEK_END)
                needs_leading_newline = existing.read(1) != b"\n"
        with path.open("a", encoding="utf-8") as handle:
            if needs_leading_newline:
                handle.write("\n")
            handle.write(line)
    _note_feedback_entry_append(
        path,
        entry,
        before_revision=before_revision,
        after_revision=_feedback_entries_revision(path),
    )
    from pallas.product.llm.feedback_embedding_cache import prefetch_trigger_embedding

    prefetch_trigger_embedding(str(entry.user_text or ""))


def _iter_feedback_entries(path: Path):
    # entries.jsonl 可能被历史脏写或非 UTF-8 污染；replace 避免整条 feedback 链路中断
    with path.open(encoding="utf-8", errors="replace") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
                yield LlmRepeaterFeedbackEntry.model_validate(payload)
            except (TypeError, ValueError):
                continue


def _dedupe_key(entry: LlmRepeaterFeedbackEntry) -> str:
    request_id = str(entry.request_id).strip()
    if request_id:
        return f"request:{request_id}"
    entry_id = str(entry.entry_id).strip()
    if entry_id:
        return f"entry:{entry_id}"
    return f"fallback:{entry.group_id}:{entry.user_id}:{entry.created_at}:{entry.reply_text}"


def _write_feedback_entries(rows: list[LlmRepeaterFeedbackEntry]) -> None:
    from pallas.core.foundation.fs_lock import atomic_write_text, interprocess_file_lock

    path = feedback_entries_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(json.dumps(item.model_dump(mode="json"), ensure_ascii=False) + "\n" for item in rows)
    with interprocess_file_lock(path.with_suffix(path.suffix + ".lock")):
        atomic_write_text(path, body)
    clear_group_feedback_entries_cache()


def _mutate_feedback_entries[T](
    mutation: Callable[[list[LlmRepeaterFeedbackEntry]], tuple[T, bool]],
) -> T:
    from pallas.core.foundation.fs_lock import atomic_write_text, interprocess_file_lock

    path = feedback_base_dir(create=False) / "entries.jsonl"
    if not path.exists():
        return mutation([])[0]
    with interprocess_file_lock(path.with_suffix(path.suffix + ".lock")):
        rows = list(_iter_feedback_entries(path))
        result, changed = mutation(rows)
        if changed:
            body = "".join(json.dumps(item.model_dump(mode="json"), ensure_ascii=False) + "\n" for item in rows)
            atomic_write_text(path, body)
    if changed:
        clear_group_feedback_entries_cache()
    return result


def feedback_archive_path(*, month: str = "") -> Path:
    """按月归档文件；默认取当前 YYYYMM。"""
    payload = str(month or "").strip()
    if not payload:
        payload = time.strftime("%Y%m")
    return feedback_base_dir() / f"entries-archive-{payload}.jsonl"


def is_retained_feedback_entry(
    item: LlmRepeaterFeedbackEntry,
    *,
    cutoff_created_at: int,
) -> bool:
    if int(item.created_at) >= cutoff_created_at:
        return True
    if str(item.corrected_reply_text or "").strip():
        return True
    if not item.eligible_for_bias:
        return True
    if str(item.scene_tier or "").strip().lower() == "strong":
        return True
    return False


def compact_feedback_entries(*, retention_days: int = 7) -> dict[str, int]:
    """压缩 entries.jsonl：超期且不被保护的条目移入按月归档文件。

    保护规则：有校正、被标记 ineligible、strong 场景。
    """
    from pallas.core.foundation.fs_lock import interprocess_file_lock

    path = feedback_base_dir(create=False) / "entries.jsonl"
    if not path.exists():
        return {"archived": 0, "retained": 0, "total": 0}

    retention_days = max(1, int(retention_days))
    now = int(time.time())
    cutoff = now - retention_days * 86400
    archive_path = feedback_archive_path()

    def mutation(rows: list[LlmRepeaterFeedbackEntry]) -> tuple[dict[str, int], bool]:
        retained: list[LlmRepeaterFeedbackEntry] = []
        archived: list[LlmRepeaterFeedbackEntry] = []
        for item in rows:
            if is_retained_feedback_entry(
                item,
                cutoff_created_at=cutoff,
            ):
                retained.append(item)
            else:
                archived.append(item)
        if not archived:
            return {"archived": 0, "retained": len(rows), "total": len(rows)}, False
        archive_body = "".join(json.dumps(item.model_dump(mode="json"), ensure_ascii=False) + "\n" for item in archived)
        with interprocess_file_lock(archive_path.with_suffix(archive_path.suffix + ".lock")):
            archive_path.parent.mkdir(parents=True, exist_ok=True)
            with archive_path.open("a", encoding="utf-8") as handle:
                handle.write(archive_body)
        rows[:] = retained
        return {
            "archived": len(archived),
            "retained": len(retained),
            "total": len(archived) + len(retained),
        }, True

    return _mutate_feedback_entries(mutation)


def _load_all_feedback_entries() -> list[LlmRepeaterFeedbackEntry]:
    path = feedback_entries_path()
    if not path.exists():
        return []
    return list(_iter_feedback_entries(path))


def _feedback_entry_matches(
    item: LlmRepeaterFeedbackEntry,
    *,
    target_entry_id: str,
    target_request_id: str,
    bot_id: int | None,
    group_id: int | None,
) -> bool:
    if not (
        (target_entry_id and str(item.entry_id).strip() == target_entry_id)
        or (target_request_id and str(item.request_id).strip() == target_request_id)
    ):
        return False
    if bot_id is None and group_id is None:
        return True
    if bot_id is None or group_id is None:
        return False
    return int(item.bot_id) == int(bot_id) and int(item.group_id) == int(group_id)


def find_feedback_entry(
    *,
    entry_id: str = "",
    request_id: str = "",
    bot_id: int | None = None,
    group_id: int | None = None,
) -> LlmRepeaterFeedbackEntry | None:
    target_entry_id = str(entry_id or "").strip()
    target_request_id = str(request_id or "").strip()
    if not target_entry_id and not target_request_id:
        return None
    if bot_id is not None and group_id is not None:
        path = feedback_base_dir(create=False) / "entries.jsonl"
        if not path.exists():
            return None
        _, _, source_rows = _group_entries_index_rows(path, group_id=int(group_id))
        for item in reversed(source_rows):
            if _feedback_entry_matches(
                item,
                target_entry_id=target_entry_id,
                target_request_id=target_request_id,
                bot_id=bot_id,
                group_id=group_id,
            ):
                return item
        return None
    for item in reversed(_load_all_feedback_entries()):
        if _feedback_entry_matches(
            item,
            target_entry_id=target_entry_id,
            target_request_id=target_request_id,
            bot_id=bot_id,
            group_id=group_id,
        ):
            return item
    return None


def find_feedback_entry_by_bot_message_id(
    *, bot_id: int, group_id: int, bot_message_id: int
) -> LlmRepeaterFeedbackEntry | None:
    global _bot_message_index_path, _bot_message_index_revision, _bot_message_index
    path = feedback_base_dir(create=False) / "entries.jsonl"
    path_key = _feedback_entries_path_key(path)
    revision = _feedback_entries_revision(path)
    with _group_entries_index_lock:
        if _bot_message_index_path != path_key or _bot_message_index_revision != revision:
            try:
                rows = deque(_iter_feedback_entries(path), maxlen=4096) if path.exists() else ()
            except OSError:
                log_rate_limited(
                    logger,
                    "warning",
                    "llm.repeater_feedback.message_lookup_read_failed",
                    "LLM feedback message lookup read failed for bot [{}] in group [{}]",
                    bot_id,
                    group_id,
                )
                return None
            _bot_message_index = {
                (item.bot_id, item.group_id, item.bot_message_id): item for item in rows if item.bot_message_id > 0
            }
            _bot_message_index_path = path_key
            _bot_message_index_revision = revision
        cached = _bot_message_index.get((int(bot_id), int(group_id), int(bot_message_id)))
    if cached is not None:
        return cached
    return _find_feedback_entry_by_bot_message_id_fallback(
        path,
        bot_id=int(bot_id),
        group_id=int(group_id),
        bot_message_id=int(bot_message_id),
    )


def _find_feedback_entry_by_bot_message_id_fallback(
    path: Path,
    *,
    bot_id: int,
    group_id: int,
    bot_message_id: int,
) -> LlmRepeaterFeedbackEntry | None:
    if not path.exists():
        return None
    try:
        with path.open(encoding="utf-8", errors="replace") as handle:
            for raw_line in handle:
                try:
                    payload = json.loads(raw_line)
                except (TypeError, ValueError):
                    continue
                if not isinstance(payload, dict):
                    continue
                try:
                    if (
                        int(payload.get("bot_id") or 0) != bot_id
                        or int(payload.get("group_id") or 0) != group_id
                        or int(payload.get("bot_message_id") or 0) != bot_message_id
                    ):
                        continue
                    return LlmRepeaterFeedbackEntry.model_validate(payload)
                except (TypeError, ValueError):
                    continue
    except OSError:
        log_rate_limited(
            logger,
            "warning",
            "llm.repeater_feedback.message_lookup_read_failed",
            "LLM feedback message lookup read failed for bot [{}] in group [{}]",
            bot_id,
            group_id,
        )
    return None


async def apply_llm_negative_feedback_for_bot_message(
    *,
    bot_id: str,
    group_id: str,
    bot_message_id: str,
    actor_id: str,
    reason: str,
) -> NegativeOutcomeApplyResult | None:
    """Apply the single group-scoped negative outcome for a delivered LLM reply."""
    try:
        entry = await asyncio.to_thread(
            find_feedback_entry_by_bot_message_id,
            bot_id=int(bot_id),
            group_id=int(group_id),
            bot_message_id=int(bot_message_id),
        )
        if entry is None:
            return None
        from pallas.product.llm.injection_feedback import apply_negative_outcome

        result = await asyncio.to_thread(
            apply_negative_outcome,
            outcome_id=f"{entry.entry_id}:not-allowed",
            bot_id=entry.bot_id,
            group_id=entry.group_id,
            reply_text=entry.reply_text,
            injection_snapshot=entry.injection_snapshot,
            actor_id=str(actor_id),
            reason=str(reason),
        )
    except Exception:
        log_rate_limited(
            logger,
            "warning",
            "llm.repeater_feedback.negative_apply_failed",
            "LLM negative feedback apply failed for bot [{}] in group [{}]",
            bot_id,
            group_id,
        )
        return None
    await apply_negative_feedback_source_decisions(entry, result)
    return result


async def apply_negative_feedback_source_decisions(
    entry: LlmRepeaterFeedbackEntry,
    result: NegativeOutcomeApplyResult,
) -> None:
    """Apply source-owned mutations after a newly persisted governance outcome."""
    from pallas.product.llm.injection_feedback import (
        begin_negative_outcome_effect,
        claim_negative_outcome_effect,
        mark_negative_outcome_effect_completed,
        release_negative_outcome_effect_claim,
    )

    expression_ids = group_scoped_expression_ids(entry, result)
    if expression_ids:
        claimed = await asyncio.to_thread(
            claim_negative_outcome_effect,
            outcome_id=result.outcome_id,
            bot_id=result.bot_id,
            group_id=result.group_id,
            kind="expression",
        )
        if claimed:
            begun = await asyncio.to_thread(
                begin_negative_outcome_effect,
                outcome_id=result.outcome_id,
                bot_id=result.bot_id,
                group_id=result.group_id,
                kind="expression",
                lease_id=claimed,
            )
            if begun:
                try:
                    await asyncio.to_thread(apply_expression_negative_feedback, entry, result, expression_ids)
                except Exception:
                    await asyncio.to_thread(
                        release_negative_outcome_effect_claim,
                        outcome_id=result.outcome_id,
                        bot_id=result.bot_id,
                        group_id=result.group_id,
                        kind="expression",
                        lease_id=claimed,
                    )
                    log_rate_limited(
                        logger,
                        "warning",
                        "llm.repeater_feedback.expression_apply_failed",
                        "LLM negative feedback expression update failed for bot [{}] in group [{}]",
                        entry.bot_id,
                        entry.group_id,
                    )
                else:
                    await asyncio.to_thread(
                        mark_negative_outcome_effect_completed,
                        outcome_id=result.outcome_id,
                        bot_id=result.bot_id,
                        group_id=result.group_id,
                        kind="expression",
                        lease_id=claimed,
                    )

    aliases = [
        decision.source_id
        for decision in result.decisions
        if decision.kind == "self_alias" and decision.remove_alias and decision.source_id
    ]
    if aliases:
        claimed = await asyncio.to_thread(
            claim_negative_outcome_effect,
            outcome_id=result.outcome_id,
            bot_id=result.bot_id,
            group_id=result.group_id,
            kind="self_alias",
        )
        if claimed:
            begun = await asyncio.to_thread(
                begin_negative_outcome_effect,
                outcome_id=result.outcome_id,
                bot_id=result.bot_id,
                group_id=result.group_id,
                kind="self_alias",
                lease_id=claimed,
            )
            if begun:
                try:
                    from pallas.product.persona.self_identity import remove_learned_self_aliases

                    await remove_learned_self_aliases(entry.bot_id, aliases)
                except Exception:
                    await asyncio.to_thread(
                        release_negative_outcome_effect_claim,
                        outcome_id=result.outcome_id,
                        bot_id=result.bot_id,
                        group_id=result.group_id,
                        kind="self_alias",
                        lease_id=claimed,
                    )
                    log_rate_limited(
                        logger,
                        "warning",
                        "llm.repeater_feedback.alias_apply_failed",
                        "LLM negative feedback alias update failed for bot [{}] in group [{}]",
                        entry.bot_id,
                        entry.group_id,
                    )
                else:
                    await asyncio.to_thread(
                        mark_negative_outcome_effect_completed,
                        outcome_id=result.outcome_id,
                        bot_id=result.bot_id,
                        group_id=result.group_id,
                        kind="self_alias",
                        lease_id=claimed,
                    )


def group_scoped_expression_ids(
    entry: LlmRepeaterFeedbackEntry,
    result: NegativeOutcomeApplyResult,
) -> list[str]:
    from pallas.product.persona.expression_bank import _group_id_from_entry_id

    expression_ids: list[str] = []
    for decision in result.decisions:
        if decision.kind != "expression" or decision.score >= 0 or not decision.source_id:
            continue
        source_group_id = _group_id_from_entry_id(decision.source_id)
        if source_group_id == int(entry.group_id):
            expression_ids.append(decision.source_id)
            continue
        log_rate_limited(
            logger,
            "warning",
            "llm.repeater_feedback.expression_scope_mismatch",
            "Ignored LLM negative feedback expression [{}] outside group [{}]",
            decision.source_id,
            entry.group_id,
        )
    return expression_ids


def apply_expression_negative_feedback(
    entry: LlmRepeaterFeedbackEntry,
    result: NegativeOutcomeApplyResult,
    expression_ids: list[str],
) -> None:
    from pallas.product.persona.expression_bank import (
        expression_scene_feedback_score,
        record_expression_outcome,
    )
    from pallas.product.persona.expression_promote import resolve_expression

    scene = entry.behavior_scene or ""
    record_expression_outcome(
        expression_ids,
        scene=scene,
        score_delta=-3,
        outcome_id=result.outcome_id,
    )
    for entry_id in expression_ids:
        if expression_scene_feedback_score(entry_id, scene=scene) <= -3:
            resolve_expression(entry_id, action="reject", reason="llm_negative_feedback")


def record_quoted_semantic_style_feedback(
    *,
    bot_id: int,
    group_id: int,
    replied_bot_message_id: int,
    following_created_at: int,
    following_user_id: int,
    following_text: str,
) -> object | None:
    entry = find_feedback_entry_by_bot_message_id(
        bot_id=bot_id,
        group_id=group_id,
        bot_message_id=replied_bot_message_id,
    )
    if entry is None or not entry.semantic_source_example_id or not entry.semantic_scene:
        return None
    from pallas.product.llm.repeater_semantic_style import (
        find_semantic_style_example,
        record_bot_style_outcome,
    )

    example = find_semantic_style_example(
        example_id=entry.semantic_source_example_id,
        bot_id=entry.bot_id,
        group_id=entry.group_id,
        scene=entry.semantic_scene,
    )
    if example is None:
        return None
    return record_bot_style_outcome(
        example,
        bot_reply_created_at=entry.created_at,
        following_created_at=following_created_at,
        following_is_bot=int(following_user_id) == int(bot_id),
        following_text=following_text,
    )


def effective_feedback_reply_text(entry: LlmRepeaterFeedbackEntry) -> str:
    corrected = str(entry.corrected_reply_text or "").strip()
    if corrected:
        return corrected
    return str(entry.reply_text or "").strip()


def set_feedback_entry_correction(
    *,
    entry_id: str = "",
    request_id: str = "",
    bot_id: int | None = None,
    group_id: int | None = None,
    corrected_reply_text: str,
    create_fields: dict[str, Any] | None = None,
) -> LlmRepeaterFeedbackEntry | None:
    text = str(corrected_reply_text or "").strip()
    if not text:
        return None
    if len(text) > _MAX_CORRECTION_LEN:
        text = text[:_MAX_CORRECTION_LEN].rstrip()

    target_entry_id = str(entry_id or "").strip()
    target_request_id = str(request_id or "").strip()
    now = int(time.time())

    def update(rows: list[LlmRepeaterFeedbackEntry]) -> tuple[LlmRepeaterFeedbackEntry | None, bool]:
        for idx, item in enumerate(rows):
            if _feedback_entry_matches(
                item,
                target_entry_id=target_entry_id,
                target_request_id=target_request_id,
                bot_id=bot_id,
                group_id=group_id,
            ):
                updated = item.model_copy(
                    update={"corrected_reply_text": text, "corrected_at": now, "eligible_for_bias": True}
                )
                rows[idx] = updated
                return updated, True
        return None, False

    updated = _mutate_feedback_entries(update)
    if updated is not None:
        return updated

    payload = dict(create_fields or {})
    if not payload:
        return None
    req_id = target_request_id or str(payload.get("request_id") or "").strip()
    if not req_id:
        req_id = f"manual-corr-{now}"
    entry = build_feedback_entry(
        entry_id=target_entry_id or req_id,
        request_id=req_id,
        bot_id=int(payload["bot_id"]),
        group_id=int(payload["group_id"]),
        user_id=int(payload["user_id"]),
        user_text=str(payload.get("user_text") or "").strip(),
        reply_text=str(payload.get("reply_text") or "").strip(),
        behavior_scene=str(payload.get("behavior_scene") or "").strip(),
        llm_route=str(payload.get("llm_route") or "").strip(),
        eligible_for_bias=True,
        corrected_reply_text=text,
        corrected_at=now,
    )
    append_feedback_entry(entry)
    return entry


def clear_feedback_entry_correction(
    *,
    entry_id: str = "",
    request_id: str = "",
    bot_id: int | None = None,
    group_id: int | None = None,
) -> LlmRepeaterFeedbackEntry | None:
    target_entry_id = str(entry_id or "").strip()
    target_request_id = str(request_id or "").strip()
    if not target_entry_id and not target_request_id:
        return None

    def clear(rows: list[LlmRepeaterFeedbackEntry]) -> tuple[LlmRepeaterFeedbackEntry | None, bool]:
        for idx, item in enumerate(rows):
            if _feedback_entry_matches(
                item,
                target_entry_id=target_entry_id,
                target_request_id=target_request_id,
                bot_id=bot_id,
                group_id=group_id,
            ):
                if not str(item.corrected_reply_text or "").strip() and not item.corrected_at:
                    return item, False
                updated = item.model_copy(update={"corrected_reply_text": "", "corrected_at": 0})
                rows[idx] = updated
                return updated, True
        return None, False

    return _mutate_feedback_entries(clear)


def set_feedback_entry_eligibility(
    *,
    entry_id: str = "",
    request_id: str = "",
    bot_id: int | None = None,
    group_id: int | None = None,
    eligible_for_bias: bool,
) -> LlmRepeaterFeedbackEntry | None:
    target_entry_id = str(entry_id or "").strip()
    target_request_id = str(request_id or "").strip()
    if not target_entry_id and not target_request_id:
        return None

    def update(rows: list[LlmRepeaterFeedbackEntry]) -> tuple[LlmRepeaterFeedbackEntry | None, bool]:
        for idx, item in enumerate(rows):
            if _feedback_entry_matches(
                item,
                target_entry_id=target_entry_id,
                target_request_id=target_request_id,
                bot_id=bot_id,
                group_id=group_id,
            ):
                target_eligible = bool(eligible_for_bias)
                if item.eligible_for_bias == target_eligible:
                    return item, False
                updated = item.model_copy(update={"eligible_for_bias": target_eligible})
                rows[idx] = updated
                return updated, True
        return None, False

    return _mutate_feedback_entries(update)


def delete_feedback_entry(
    *,
    entry_id: str = "",
    request_id: str = "",
    bot_id: int | None = None,
    group_id: int | None = None,
) -> bool:
    target_entry_id = str(entry_id or "").strip()
    target_request_id = str(request_id or "").strip()
    if not target_entry_id and not target_request_id:
        return False

    def delete(rows: list[LlmRepeaterFeedbackEntry]) -> tuple[bool, bool]:
        kept = [
            item
            for item in rows
            if not (
                _feedback_entry_matches(
                    item,
                    target_entry_id=target_entry_id,
                    target_request_id=target_request_id,
                    bot_id=bot_id,
                    group_id=group_id,
                )
            )
        ]
        removed = len(kept) != len(rows)
        if removed:
            rows[:] = kept
        return removed, removed

    return _mutate_feedback_entries(delete)


def list_feedback_entries_for_session(
    *,
    bot_id: int,
    group_id: int,
    user_id: int,
    limit: int = 100,
) -> list[LlmRepeaterFeedbackEntry]:
    path = feedback_entries_path()
    if not path.exists():
        return []
    window_size = max(1, int(limit)) * _RECENT_WINDOW_MULTIPLIER
    target_group_id = int(group_id)
    target_bot_id = int(bot_id)
    target_user_id = int(user_id)
    _, _, source_rows = _group_entries_index_rows(path, group_id=target_group_id)
    recent: deque[LlmRepeaterFeedbackEntry] = deque(
        (item for item in source_rows if int(item.bot_id) == target_bot_id and int(item.user_id) == target_user_id),
        maxlen=window_size,
    )
    deduped: list[LlmRepeaterFeedbackEntry] = []
    seen_ids: set[str] = set()
    for item in reversed(recent):
        dedupe_key = _dedupe_key(item)
        if dedupe_key in seen_ids:
            continue
        seen_ids.add(dedupe_key)
        deduped.append(item)
    deduped.reverse()
    return deduped[-max(1, int(limit)) :]


def list_group_feedback_entries(
    *, group_id: int, limit: int = 50, bot_id: int | None = None
) -> list[LlmRepeaterFeedbackEntry]:
    path = feedback_entries_path()
    if not path.exists():
        return []
    lim = max(1, int(limit))
    target_group_id = int(group_id)
    target_bot_id = int(bot_id) if bot_id is not None else None
    path_key, group_revision, source_rows = _group_entries_index_rows(path, group_id=target_group_id)
    key = (path_key, target_group_id, target_bot_id, lim)
    now = time.monotonic()
    window_size = lim * _RECENT_WINDOW_MULTIPLIER
    with _group_entries_index_lock:
        cached = _group_entries_cache.get(key)
        if cached is not None:
            expire_at, cached_revision, rows = cached
            if now < expire_at and cached_revision == group_revision:
                return list(rows)
    recent: deque[LlmRepeaterFeedbackEntry] = deque(
        (item for item in source_rows if target_bot_id is None or item.bot_id == target_bot_id),
        maxlen=window_size,
    )
    deduped: list[LlmRepeaterFeedbackEntry] = []
    seen_ids: set[str] = set()
    for item in reversed(recent):
        dedupe_key = _dedupe_key(item)
        if dedupe_key in seen_ids:
            continue
        seen_ids.add(dedupe_key)
        deduped.append(item)
    deduped.reverse()
    rows = deduped[-lim:]
    with _group_entries_index_lock:
        if _group_entries_revisions.get(target_group_id, 0) == group_revision:
            _group_entries_cache[key] = (now + _GROUP_ENTRIES_CACHE_TTL_SEC, group_revision, list(rows))
            while len(_group_entries_cache) > _GROUP_ENTRIES_CACHE_MAX:
                _group_entries_cache.pop(next(iter(_group_entries_cache)))
    return rows


def group_feedback_bias_snapshot(
    *,
    bot_id: int | None = None,
    group_id: int,
    limit: int = 50,
    user_text: str = "",
    behavior_scene: str = "",
    hotpath: bool = False,
) -> dict[str, Any]:
    from pallas.product.llm.feedback_learning import build_feedback_bias_snapshot_data

    return build_feedback_bias_snapshot_data(
        bot_id=int(bot_id) if bot_id is not None else None,
        group_id=int(group_id),
        limit=int(limit),
        user_text=str(user_text or ""),
        behavior_scene=str(behavior_scene or ""),
        hotpath=bool(hotpath),
    )


def should_append_feedback_for_task(task_type: str) -> bool:
    return can_collect_feedback() and is_feedback_task_type(task_type)
