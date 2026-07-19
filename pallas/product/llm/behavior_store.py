"""Persistence helpers for llm_chat behavior patterns and run records."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pallas.core.foundation.paths import plugin_data_dir

from .behavior import (
    BehaviorOutcome,
    BehaviorPattern,
    BehaviorRun,
    default_behavior_pattern_seeds,
    map_behavior_outcome_score,
)


def _base_dir() -> Path:
    env_dir = str(__import__("os").environ.get("PALLAS_DATA_DIR") or "").strip()
    if env_dir:
        root = Path(env_dir)
        root.mkdir(parents=True, exist_ok=True)
        path = root / "llm_behavior"
        path.mkdir(parents=True, exist_ok=True)
        return path
    path = plugin_data_dir("pb_webui", create=True) / "llm_behavior"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _patterns_path() -> Path:
    return _base_dir() / "patterns.json"


def _runs_path() -> Path:
    return _base_dir() / "runs.jsonl"


def save_behavior_patterns(patterns: list[BehaviorPattern]) -> None:
    from pallas.core.foundation.fs_lock import atomic_write_text, interprocess_file_lock

    path = _patterns_path()
    body = json.dumps([item.model_dump(mode="json") for item in patterns], ensure_ascii=False, indent=2)
    with interprocess_file_lock(path.with_suffix(path.suffix + ".lock")):
        atomic_write_text(path, body)


def ensure_default_behavior_patterns() -> list[BehaviorPattern]:
    """patterns.json 不存在时写入全局默认种子；已有文件（含空列表）不覆盖。"""
    path = _patterns_path()
    if path.exists():
        return list_behavior_patterns()
    seeds = default_behavior_pattern_seeds()
    save_behavior_patterns(seeds)
    return seeds


def list_behavior_patterns() -> list[BehaviorPattern]:
    path = _patterns_path()
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8") or "[]")
    return [BehaviorPattern.model_validate(item) for item in payload if isinstance(item, dict)]


def upsert_behavior_pattern(pattern: BehaviorPattern) -> BehaviorPattern:
    rows = list_behavior_patterns()
    replaced = False
    for idx, item in enumerate(rows):
        if item.pattern_id != pattern.pattern_id:
            continue
        rows[idx] = pattern
        replaced = True
        break
    if not replaced:
        rows.append(pattern)
    save_behavior_patterns(rows)
    return pattern


def delete_behavior_pattern(pattern_id: str) -> bool:
    target_id = str(pattern_id or "").strip()
    if not target_id:
        return False
    rows = list_behavior_patterns()
    kept = [item for item in rows if item.pattern_id != target_id]
    if len(kept) == len(rows):
        return False
    save_behavior_patterns(kept)
    return True


def append_behavior_run(run: BehaviorRun) -> None:
    from pallas.core.foundation.fs_lock import interprocess_file_lock

    path = _runs_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(run.model_dump(mode="json"), ensure_ascii=False) + "\n"
    with interprocess_file_lock(path.with_suffix(path.suffix + ".lock")):
        with path.open("a", encoding="utf-8") as f:
            f.write(line)


def list_behavior_runs(*, limit: int = 50) -> list[BehaviorRun]:
    path = _runs_path()
    if not path.exists():
        return []
    rows: list[BehaviorRun] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(BehaviorRun.model_validate(json.loads(line)))
    return rows[-max(1, int(limit)) :]


def list_behavior_runs_for_session(
    *,
    bot_id: int,
    group_id: int | None,
    user_id: int,
    limit: int = 50,
) -> list[BehaviorRun]:
    rows = [
        item
        for item in list_behavior_runs(limit=max(limit * 4, limit))
        if int(item.user_id or 0) == int(user_id)
        and int(item.group_id or 0) == int(group_id or 0)
        and int(item.bot_id or 0) == int(bot_id)
    ]
    return rows[-max(1, int(limit)) :]


def update_behavior_run_annotation(
    request_id: str,
    *,
    labels: list[str],
    final_outcome: BehaviorOutcome | str | None = None,
    disabled: bool | None = None,
) -> BehaviorRun | None:
    rows = list_behavior_runs(limit=10_000)
    updated: BehaviorRun | None = None
    for idx, item in enumerate(rows):
        if item.request_id != request_id:
            continue
        if labels:
            item.manual_labels = [str(label).strip() for label in labels if str(label).strip()]
        if final_outcome:
            item.final_outcome = (
                final_outcome if isinstance(final_outcome, BehaviorOutcome) else BehaviorOutcome(str(final_outcome))
            )
        if disabled is not None:
            item.disabled = bool(disabled)
        rows[idx] = item
        updated = item
        break
    if updated is None:
        return None
    from pallas.core.foundation.fs_lock import atomic_write_text, interprocess_file_lock

    path = _runs_path()
    body = "".join(json.dumps(item.model_dump(mode="json"), ensure_ascii=False) + "\n" for item in rows)
    with interprocess_file_lock(path.with_suffix(path.suffix + ".lock")):
        atomic_write_text(path, body)
    return updated


def settle_behavior_run_outcome(
    request_id: str,
    *,
    final_outcome: BehaviorOutcome | str,
    auto_feedback_payload: dict[str, Any] | None = None,
) -> BehaviorRun | None:
    rows = list_behavior_runs(limit=10_000)
    updated: BehaviorRun | None = None
    outcome = final_outcome if isinstance(final_outcome, BehaviorOutcome) else BehaviorOutcome(str(final_outcome))
    score_delta = map_behavior_outcome_score(outcome)
    for idx, item in enumerate(rows):
        if item.request_id != request_id or item.final_outcome is not None:
            continue
        item.final_outcome = outcome
        item.score_delta = score_delta
        merged_payload = dict(item.auto_feedback_payload or {})
        merged_payload.update(dict(auto_feedback_payload or {}))
        item.auto_feedback_payload = merged_payload
        rows[idx] = item
        updated = item
        break
    if updated is None:
        return None
    from pallas.core.foundation.fs_lock import atomic_write_text, interprocess_file_lock

    path = _runs_path()
    body = "".join(json.dumps(item.model_dump(mode="json"), ensure_ascii=False) + "\n" for item in rows)
    with interprocess_file_lock(path.with_suffix(path.suffix + ".lock")):
        atomic_write_text(path, body)
    if updated.selected_pattern_ids and score_delta:
        patterns = list_behavior_patterns()
        changed = False
        for idx, item in enumerate(patterns):
            if item.pattern_id not in updated.selected_pattern_ids:
                continue
            item.success_score = int(item.success_score) + score_delta
            patterns[idx] = item
            changed = True
        if changed:
            save_behavior_patterns(patterns)
    return updated


def behavior_run_public_dict(run: BehaviorRun) -> dict[str, Any]:
    return run.model_dump(mode="json")
