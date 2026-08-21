"""Persistent per-group expression bank entries.

Storage layout (per group sharded, append + periodic merge):
  expression_bank/pending/<group_id>.jsonl   deltas appended on write
  expression_bank/merged/<group_id>.jsonl    compacted authority

Writes append O(1) deltas into pending. Readers fold (merged + pending) for
their own group, so data is visible immediately without a merge. A periodic
merge compacts pending into merged and truncates pending.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from pallas.core.foundation.paths import plugin_data_dir
from pallas.product.persona.occasion import normalize_occasion_tag

ExpressionSource = Literal["group_observe", "llm_success"]
ExpressionStatus = Literal["shadow", "active", "rejected"]
ExpressionKey = tuple[str, str]

_ENTRY_ID_RE = re.compile(r"^expr-(\d+)-", re.ASCII)


class ExpressionEntry(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    entry_id: str
    group_id: int
    occasion: str
    saying: str
    support: int = 1
    source: ExpressionSource
    channel: str
    scene_tier: str
    status: ExpressionStatus
    affect_hint: str
    bot_id: int = 0
    created_at: int
    updated_at: int
    rejected_reason: str = ""
    scene_feedback: dict[str, dict[str, int]] = Field(default_factory=dict)
    applied_outcome_ids: list[str] = Field(default_factory=list)

    @field_validator("occasion", mode="before")
    @classmethod
    def normalize_occasion(cls, value: object) -> str:
        return normalize_occasion_tag(str(value or ""))


def _expression_bank_base_dir(*, create: bool) -> Path:
    env_dir = str(os.environ.get("PALLAS_DATA_DIR") or "").strip()
    if env_dir:
        root = Path(env_dir)
        if create:
            root.mkdir(parents=True, exist_ok=True)
        path = root / "expression_bank"
    else:
        path = plugin_data_dir("pb_webui", create=create) / "expression_bank"
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def expression_bank_base_dir() -> Path:
    return _expression_bank_base_dir(create=True)


def _pending_dir(*, create: bool = True) -> Path:
    path = _expression_bank_base_dir(create=create) / "pending"
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def _merged_dir(*, create: bool = True) -> Path:
    path = _expression_bank_base_dir(create=create) / "merged"
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def expression_entries_path() -> Path:
    """Legacy single-file path; kept for one-time migration and compatibility."""
    return expression_bank_base_dir() / "entries.jsonl"


def _shard_path(group_id: int, *, pending: bool, create: bool = True) -> Path:
    shard_dir = _pending_dir(create=create) if pending else _merged_dir(create=create)
    return shard_dir / f"{int(group_id)}.jsonl"


def _group_id_from_entry_id(entry_id: str) -> int:
    match = _ENTRY_ID_RE.match(str(entry_id or ""))
    if match:
        return int(match.group(1))
    return 0


def _write_lines_append(path: Path, rows: list[ExpressionEntry]) -> None:
    body = "".join(json.dumps(item.model_dump(mode="json"), ensure_ascii=False) + "\n" for item in rows)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(body)


def _write_lines_atomic(path: Path, rows: list[ExpressionEntry]) -> None:
    from pallas.core.foundation.fs_lock import atomic_write_text

    body = "".join(json.dumps(item.model_dump(mode="json"), ensure_ascii=False) + "\n" for item in rows)
    atomic_write_text(path, body)


def _iter_rows(path: Path):
    if not path.exists():
        return
    with path.open(encoding="utf-8", errors="replace") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            try:
                yield ExpressionEntry.model_validate(json.loads(line))
            except (TypeError, ValueError):
                continue


def normalize_expression_key(occasion: str, saying: str) -> ExpressionKey:
    return (
        normalize_occasion_tag(occasion)[:20].strip(),
        str(saying or "").strip()[:20].strip(),
    )


def build_entry_id(group_id: int, key: ExpressionKey) -> str:
    occasion, saying = normalize_expression_key(*key)
    digest = hashlib.sha256(f"{int(group_id)}\n{occasion}\n{saying}".encode()).hexdigest()[:12]
    return f"expr-{int(group_id)}-{digest}"


def _merge_rows(existing: list[ExpressionEntry], deltas: list[ExpressionEntry]) -> list[ExpressionEntry]:
    index: dict[str, ExpressionEntry] = {}
    for row in existing:
        index[row.entry_id] = row
    for delta in deltas:
        current = index.get(delta.entry_id)
        if current is None:
            # Deltas with empty saying are pure feedback/outcome updates; only
            # material entries create new rows.
            if delta.saying:
                index[delta.entry_id] = delta
            continue
        new_outcomes = [outcome for outcome in delta.applied_outcome_ids if outcome not in current.applied_outcome_ids]
        feedback = {key: dict(value) for key, value in current.scene_feedback.items()}
        if new_outcomes:
            for scene, stats in delta.scene_feedback.items():
                merged_stats = feedback.setdefault(scene, {"uses": 0, "score": 0})
                merged_stats["uses"] = int(merged_stats.get("uses", 0)) + int(stats.get("uses", 0))
                merged_stats["score"] = int(merged_stats.get("score", 0)) + int(stats.get("score", 0))
        combined_outcomes = list({*current.applied_outcome_ids, *delta.applied_outcome_ids})
        if not delta.saying:
            # Pure outcome update keeps all material fields untouched.
            index[delta.entry_id] = current.model_copy(
                update={"scene_feedback": feedback, "applied_outcome_ids": combined_outcomes}
            )
            continue
        source = "llm_success" if "llm_success" in {current.source, delta.source} else "group_observe"
        is_status_delta = int(delta.support) == 0
        if is_status_delta:
            status = delta.status
            rejected_reason = delta.rejected_reason
        else:
            status = current.status if current.status == "rejected" else delta.status
            rejected_reason = delta.rejected_reason or current.rejected_reason
        merged = current.model_copy(
            update={
                "support": max(1, int(current.support)) + max(0, int(delta.support)),
                "source": source,
                "status": status,
                "updated_at": max(current.updated_at, delta.updated_at),
                "scene_feedback": feedback,
                "applied_outcome_ids": combined_outcomes,
                "rejected_reason": rejected_reason,
            }
        )
        index[delta.entry_id] = merged
    return list(index.values())


def _append_shard(group_id: int, entries: list[ExpressionEntry]) -> None:
    from pallas.core.foundation.fs_lock import interprocess_file_lock

    if not entries:
        return
    path = _shard_path(group_id, pending=True)
    with interprocess_file_lock(path.with_suffix(path.suffix + ".lock")):
        _write_lines_append(path, entries)


def _group_combined_rows(group_id: int, *, create: bool = True) -> list[ExpressionEntry]:
    """Fold pending deltas over merged authority for one group."""
    merged = list(_iter_rows(_shard_path(group_id, pending=False, create=create)))
    pending = list(_iter_rows(_shard_path(group_id, pending=True, create=create)))
    if not pending:
        return merged
    return _merge_rows(merged, pending)


def merge_group_expressions(group_id: int) -> None:
    """Compress this group's pending deltas into merged and truncate pending."""
    from pallas.core.foundation.fs_lock import interprocess_file_lock

    gid = int(group_id)
    path = _shard_path(gid, pending=True)
    with interprocess_file_lock(path.with_suffix(path.suffix + ".lock")):
        pending = list(_iter_rows(path))
        if not pending:
            return
        merged = _merge_rows(list(_iter_rows(_shard_path(gid, pending=False))), pending)
        _write_lines_atomic(_shard_path(gid, pending=False), merged)
        path.unlink(missing_ok=True)


def merge_all_pending_expressions(limit: int = 256) -> int:
    """Compress up to `limit` groups with pending deltas. Returns count merged."""
    merged_count = 0
    for path in sorted(_pending_dir().glob("*.jsonl")):
        if merged_count >= max(0, int(limit)):
            break
        name = path.name
        if not name.endswith(".jsonl") or name == ".jsonl":
            continue
        try:
            gid = int(path.stem)
        except ValueError:
            continue
        merge_group_expressions(gid)
        merged_count += 1
    return merged_count


def append_or_merge_expression(entry: ExpressionEntry) -> ExpressionEntry:
    """Append a delta (O(1)) and return the folded entry for this group."""
    key = normalize_expression_key(entry.occasion, entry.saying)
    canonical_entry = entry.model_copy(
        update={
            "entry_id": build_entry_id(entry.group_id, key),
            "group_id": int(entry.group_id),
            "occasion": key[0],
            "saying": key[1],
            "support": max(1, int(entry.support)),
        }
    )
    gid = int(canonical_entry.group_id)
    from pallas.core.foundation.fs_lock import interprocess_file_lock

    path = _shard_path(gid, pending=True)
    with interprocess_file_lock(path.with_suffix(path.suffix + ".lock")):
        combined = _merge_rows(_group_combined_rows(gid), [canonical_entry])
        matched = next((row for row in combined if row.entry_id == canonical_entry.entry_id), canonical_entry)
        _write_lines_append(path, [canonical_entry])
        return matched


def record_expression_outcome(entry_ids: list[str], *, scene: str, score_delta: int, outcome_id: str) -> None:
    targets = {str(item).strip() for item in entry_ids if str(item).strip()}
    if not targets:
        return
    scene_key = normalize_occasion_tag(str(scene or ""))
    now = int(time.time())
    by_group: dict[int, list[ExpressionEntry]] = {}
    for target in targets:
        gid = _group_id_from_entry_id(target)
        if gid <= 0:
            continue
        by_group.setdefault(gid, []).append(
            ExpressionEntry(
                entry_id=target,
                group_id=gid,
                occasion="",
                saying="",
                support=0,
                source="group_observe",
                channel="",
                scene_tier="",
                status="shadow",
                affect_hint="",
                created_at=now,
                updated_at=now,
                scene_feedback={scene_key: {"uses": 1, "score": int(score_delta)}} if scene_key else {},
                applied_outcome_ids=[outcome_id],
            )
        )
    for gid, deltas in sorted(by_group.items()):
        _append_shard(gid, deltas)


def expression_scene_feedback_score(entry_id: str, *, scene: str) -> int:
    target_id = str(entry_id or "").strip()
    group_id = _group_id_from_entry_id(target_id)
    scene_key = normalize_occasion_tag(str(scene or ""))
    if not target_id or group_id <= 0 or not scene_key:
        return 0
    entry = next(
        (item for item in _group_combined_rows(group_id, create=False) if item.entry_id == target_id),
        None,
    )
    if entry is None:
        return 0
    return int(entry.scene_feedback.get(scene_key, {}).get("score", 0))


def get_group_expression(*, group_id: int, entry_id: str) -> ExpressionEntry | None:
    """Return one exact entry from its group shard without creating storage directories."""
    target_group_id = int(group_id)
    target_entry_id = str(entry_id or "").strip()
    if not target_entry_id or _group_id_from_entry_id(target_entry_id) != target_group_id:
        return None
    return next(
        (item for item in _group_combined_rows(target_group_id, create=False) if item.entry_id == target_entry_id),
        None,
    )


def migrate_legacy_expression_entries() -> bool:
    """One-time migration from the legacy single-file entries.jsonl to shards.

    Returns whether a legacy file was found and migrated.
    """
    legacy = expression_entries_path()
    if not legacy.exists():
        return False
    rows = list(_iter_rows(legacy))
    by_group: dict[int, list[ExpressionEntry]] = {}
    for row in rows:
        by_group.setdefault(int(row.group_id), []).append(row)
    for gid, group_rows in sorted(by_group.items()):
        merged = _merge_rows([], group_rows)
        _write_lines_atomic(_shard_path(gid, pending=False), merged)
    legacy.replace(legacy.with_suffix(".jsonl.migrated.bak"))
    return True


def _load_all_rows() -> list[ExpressionEntry]:
    """Read every group's folded state; used by legacy consumers, not hot paths."""
    rows: list[ExpressionEntry] = []
    for path in sorted(_merged_dir().glob("*.jsonl")):
        rows.extend(_iter_rows(path))
    return rows


def list_group_expressions(
    group_id: int,
    *,
    status: ExpressionStatus | None = None,
    limit: int = 50,
) -> list[ExpressionEntry]:
    """Return this group's entries (pending folded over merged)."""
    target_group_id = int(group_id)
    rows = [item for item in _group_combined_rows(target_group_id) if status is None or item.status == status]
    return rows[-max(1, int(limit)) :]
