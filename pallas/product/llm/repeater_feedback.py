"""Soft feedback primitives for llm_chat -> repeater."""

from __future__ import annotations

import json
import os
import re
import time
from collections import deque
from pathlib import Path
from threading import RLock
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from pallas.core.foundation.paths import plugin_data_dir
from pallas.core.platform.ai_callback.task_types import LLM_CHAT_TASK_TYPE
from pallas.product.llm.kernel.memory_governance import (
    can_collect_feedback,
    can_promote_writeback,
)

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
    eligible_for_writeback: bool = False
    corrected_reply_text: str = ""
    corrected_at: int = 0
    bot_message_id: int = 0
    semantic_source_example_id: str = ""
    semantic_scene: str = ""


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


def feedback_base_dir() -> Path:
    env_dir = str(os.environ.get("PALLAS_DATA_DIR") or "").strip()
    if env_dir:
        root = Path(env_dir)
        root.mkdir(parents=True, exist_ok=True)
        path = root / "llm_repeater_feedback"
        path.mkdir(parents=True, exist_ok=True)
        return path
    path = plugin_data_dir("pb_webui", create=True) / "llm_repeater_feedback"
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
        eligible_for_writeback=bool(kwargs.get("eligible_for_writeback", False)),
        corrected_reply_text=str(kwargs.get("corrected_reply_text") or "").strip(),
        corrected_at=int(kwargs.get("corrected_at") or 0),
        bot_message_id=int(kwargs.get("bot_message_id") or 0),
        semantic_source_example_id=str(kwargs.get("semantic_source_example_id") or "").strip(),
        semantic_scene=str(kwargs.get("semantic_scene") or "").strip(),
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
    from pallas.product.llm.promotion_candidates import note_feedback_entry_for_promotion

    prefetch_trigger_embedding(str(entry.user_text or ""))
    note_feedback_entry_for_promotion(entry)


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


def _load_all_feedback_entries() -> list[LlmRepeaterFeedbackEntry]:
    path = feedback_entries_path()
    if not path.exists():
        return []
    return list(_iter_feedback_entries(path))


def find_feedback_entry(*, entry_id: str = "", request_id: str = "") -> LlmRepeaterFeedbackEntry | None:
    target_entry_id = str(entry_id or "").strip()
    target_request_id = str(request_id or "").strip()
    if not target_entry_id and not target_request_id:
        return None
    for item in reversed(_load_all_feedback_entries()):
        if target_entry_id and str(item.entry_id).strip() == target_entry_id:
            return item
        if target_request_id and str(item.request_id).strip() == target_request_id:
            return item
    return None


def find_feedback_entry_by_bot_message_id(
    *, bot_id: int, group_id: int, bot_message_id: int
) -> LlmRepeaterFeedbackEntry | None:
    global _bot_message_index_path, _bot_message_index_revision, _bot_message_index
    path = feedback_entries_path()
    path_key = _feedback_entries_path_key(path)
    revision = _feedback_entries_revision(path)
    with _group_entries_index_lock:
        if _bot_message_index_path != path_key or _bot_message_index_revision != revision:
            rows = deque(_iter_feedback_entries(path), maxlen=4096) if path.exists() else ()
            _bot_message_index = {
                (item.bot_id, item.group_id, item.bot_message_id): item for item in rows if item.bot_message_id > 0
            }
            _bot_message_index_path = path_key
            _bot_message_index_revision = revision
        return _bot_message_index.get((int(bot_id), int(group_id), int(bot_message_id)))


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
    rows = _load_all_feedback_entries()
    for idx, item in enumerate(rows):
        matched = False
        if target_entry_id and str(item.entry_id).strip() == target_entry_id:
            matched = True
        elif target_request_id and str(item.request_id).strip() == target_request_id:
            matched = True
        if not matched:
            continue
        item.corrected_reply_text = text
        item.corrected_at = now
        item.eligible_for_bias = True
        rows[idx] = item
        _write_feedback_entries(rows)
        from pallas.product.llm.promotion_candidates import note_feedback_entry_for_promotion

        note_feedback_entry_for_promotion(item)
        return item

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


def clear_feedback_entry_correction(*, entry_id: str = "", request_id: str = "") -> LlmRepeaterFeedbackEntry | None:
    target_entry_id = str(entry_id or "").strip()
    target_request_id = str(request_id or "").strip()
    if not target_entry_id and not target_request_id:
        return None
    rows = _load_all_feedback_entries()
    updated: LlmRepeaterFeedbackEntry | None = None
    for idx, item in enumerate(rows):
        matched = False
        if target_entry_id and str(item.entry_id).strip() == target_entry_id:
            matched = True
        elif target_request_id and str(item.request_id).strip() == target_request_id:
            matched = True
        if not matched:
            continue
        item.corrected_reply_text = ""
        item.corrected_at = 0
        rows[idx] = item
        updated = item
        break
    if updated is None:
        return None
    _write_feedback_entries(rows)
    return updated


def set_feedback_entry_eligibility(
    *,
    entry_id: str = "",
    request_id: str = "",
    eligible_for_bias: bool,
) -> LlmRepeaterFeedbackEntry | None:
    target_entry_id = str(entry_id or "").strip()
    target_request_id = str(request_id or "").strip()
    if not target_entry_id and not target_request_id:
        return None
    rows = _load_all_feedback_entries()
    updated: LlmRepeaterFeedbackEntry | None = None
    for idx, item in enumerate(rows):
        matched = False
        if target_entry_id and str(item.entry_id).strip() == target_entry_id:
            matched = True
        elif target_request_id and str(item.request_id).strip() == target_request_id:
            matched = True
        if not matched:
            continue
        item.eligible_for_bias = bool(eligible_for_bias)
        rows[idx] = item
        updated = item
        break
    if updated is None:
        return None
    _write_feedback_entries(rows)
    return updated


def delete_feedback_entry(*, entry_id: str = "", request_id: str = "") -> bool:
    target_entry_id = str(entry_id or "").strip()
    target_request_id = str(request_id or "").strip()
    if not target_entry_id and not target_request_id:
        return False
    rows = _load_all_feedback_entries()
    kept: list[LlmRepeaterFeedbackEntry] = []
    removed = False
    for item in rows:
        matched = False
        if target_entry_id and str(item.entry_id).strip() == target_entry_id:
            matched = True
        elif target_request_id and str(item.request_id).strip() == target_request_id:
            matched = True
        if matched:
            removed = True
            continue
        kept.append(item)
    if not removed:
        return False
    _write_feedback_entries(kept)
    return True


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
    recent: deque[LlmRepeaterFeedbackEntry] = deque(maxlen=window_size)
    target_group_id = int(group_id)
    target_bot_id = int(bot_id)
    target_user_id = int(user_id)
    for item in _iter_feedback_entries(path):
        if int(item.group_id) != target_group_id:
            continue
        if int(item.bot_id) != target_bot_id:
            continue
        if int(item.user_id) != target_user_id:
            continue
        recent.append(item)
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


def list_group_feedback_entries(*, group_id: int, limit: int = 50) -> list[LlmRepeaterFeedbackEntry]:
    path = feedback_entries_path()
    if not path.exists():
        return []
    lim = max(1, int(limit))
    target_group_id = int(group_id)
    path_key, group_revision, source_rows = _group_entries_index_rows(path, group_id=target_group_id)
    key = (path_key, target_group_id, lim)
    now = time.monotonic()
    window_size = lim * _RECENT_WINDOW_MULTIPLIER
    with _group_entries_index_lock:
        cached = _group_entries_cache.get(key)
        if cached is not None:
            expire_at, cached_revision, rows = cached
            if now < expire_at and cached_revision == group_revision:
                return list(rows)
    recent: deque[LlmRepeaterFeedbackEntry] = deque(source_rows, maxlen=window_size)
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


def is_reply_safe_for_auto_promote(reply_text: str, *, trigger_text: str = "") -> bool:
    plain = str(reply_text or "").strip()
    if not plain or len(plain) > _MAX_REPLY_LEN:
        return False
    if is_systemish_promote_text(plain, trigger_text):
        return False
    from pallas.product.llm.corpus_contamination import is_feedback_reply_collectable

    if not is_feedback_reply_collectable(plain):
        return False
    from pallas.product.llm.feedback_learning import is_reply_safe_for_shaped_writeback

    return is_reply_safe_for_shaped_writeback(plain)


def group_feedback_bias_snapshot(
    *,
    group_id: int,
    limit: int = 50,
    user_text: str = "",
    behavior_scene: str = "",
    hotpath: bool = False,
) -> dict[str, Any]:
    from pallas.product.llm.feedback_learning import build_feedback_bias_snapshot_data

    return build_feedback_bias_snapshot_data(
        group_id=int(group_id),
        limit=int(limit),
        user_text=str(user_text or ""),
        behavior_scene=str(behavior_scene or ""),
        hotpath=bool(hotpath),
    )


def should_append_feedback_for_task(task_type: str) -> bool:
    return can_collect_feedback() and is_feedback_task_type(task_type)


def promotion_allowed() -> bool:
    return can_promote_writeback()
