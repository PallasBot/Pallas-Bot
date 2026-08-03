"""Persist and compare explicit offline LLM quality runs."""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

from pallas.core.foundation.paths import plugin_data_dir
from pallas.product.llm.offline_quality_eval import (
    OfflineQualityCase,
    OfflineQualityResult,
    summarize_quality_matrix,
)


def default_quality_baseline_path() -> Path:
    env_dir = str(os.environ.get("PALLAS_DATA_DIR") or "").strip()
    if env_dir:
        root = Path(env_dir) / "pallas_llm"
    else:
        root = plugin_data_dir("pb_webui", create=True) / "pallas_llm"
    root.mkdir(parents=True, exist_ok=True)
    return root / "quality_baselines.jsonl"


def quality_result_rows(
    cases: tuple[OfflineQualityCase, ...] | list[OfflineQualityCase],
    results: tuple[OfflineQualityResult, ...] | list[OfflineQualityResult],
    *,
    run_id: str,
    created_at: int,
    matrix_version: str,
) -> list[dict[str, Any]]:
    case_by_id = {case.case_id: case for case in cases}
    rows: list[dict[str, Any]] = []
    for result in results:
        case = case_by_id.get(result.case_id)
        if case is None:
            continue
        judge = result.judge
        rows.append({
            "run_id": str(run_id),
            "created_at": int(created_at),
            "matrix_version": str(matrix_version),
            "persona_id": case.persona_id or "unassigned",
            "case_id": case.case_id,
            "scene": case.scene or "unassigned",
            "scores": dict(judge.scores if judge is not None else result.heuristic_scores),
            "heuristic_scores": dict(result.heuristic_scores),
            "judge": ({"verdict": judge.verdict, "reason_ids": list(judge.reason_ids)} if judge is not None else None),
            "firewall_rule_ids": list(result.firewall_rule_ids),
        })
    return rows


def append_quality_baseline_rows(rows: list[dict[str, Any]], *, path: Path | None = None) -> Path:
    from pallas.core.foundation.fs_lock import interprocess_file_lock

    target = Path(path) if path is not None else default_quality_baseline_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    with interprocess_file_lock(target.with_suffix(target.suffix + ".lock")):
        with target.open("a", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(dict(row), ensure_ascii=False, separators=(",", ":")) + "\n")
    return target


def record_quality_baseline(
    cases: tuple[OfflineQualityCase, ...] | list[OfflineQualityCase],
    results: tuple[OfflineQualityResult, ...] | list[OfflineQualityResult],
    *,
    matrix_version: str,
    path: Path | None = None,
    run_id: str | None = None,
    created_at: int | None = None,
) -> tuple[str, list[dict[str, Any]], Path]:
    resolved_run_id = str(run_id or f"quality-{uuid.uuid4().hex[:12]}")
    rows = quality_result_rows(
        cases,
        results,
        run_id=resolved_run_id,
        created_at=int(time.time()) if created_at is None else int(created_at),
        matrix_version=matrix_version,
    )
    return resolved_run_id, rows, append_quality_baseline_rows(rows, path=path)


def read_quality_baseline_rows(*, path: Path | None = None, limit: int = 2_000) -> list[dict[str, Any]]:
    target = Path(path) if path is not None else default_quality_baseline_path()
    if not target.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in target.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows[-max(1, int(limit)) :]


def latest_quality_run_rows(
    rows: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    matrix_version: str,
) -> list[dict[str, Any]]:
    target_version = str(matrix_version)
    matches = [row for row in rows if str(row.get("matrix_version") or "") == target_version]
    if not matches:
        return []
    latest = max(enumerate(matches), key=lambda item: (int(item[1].get("created_at") or 0), item[0]))[1]
    run_id = str(latest.get("run_id") or "")
    return [row for row in matches if str(row.get("run_id") or "") == run_id]


def summarize_quality_baseline(rows: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> dict[str, Any]:
    matrix_rows = []
    rule_ids: set[str] = set()
    for row in rows:
        case = OfflineQualityCase(
            case_id=str(row.get("case_id") or ""),
            user_text="",
            social_action="ACK",
            reply_target="fact",
            persona_id=str(row.get("persona_id") or "unassigned"),
            scene=str(row.get("scene") or "unassigned"),
        )
        scores = row.get("scores")
        raw_rules = row.get("firewall_rule_ids")
        normalized_rules = (
            tuple(str(item) for item in raw_rules if str(item).strip()) if isinstance(raw_rules, list) else ()
        )
        matrix_rows.append((case, scores if isinstance(scores, dict) else {}, normalized_rules))
        rule_ids.update(normalized_rules)
    summary = summarize_quality_matrix(matrix_rows)
    summary["rule_ids"] = sorted(rule_ids)
    return summary


def compare_quality_baselines(
    current: dict[str, Any], previous: dict[str, Any]
) -> dict[str, list[dict[str, Any]] | list[str]]:
    score_regressions: list[dict[str, Any]] = []
    for bucket_name in ("by_persona", "by_scene", "by_rule_id"):
        current_bucket = current.get(bucket_name)
        previous_bucket = previous.get(bucket_name)
        if not isinstance(current_bucket, dict) or not isinstance(previous_bucket, dict):
            continue
        for key, current_value in current_bucket.items():
            previous_value = previous_bucket.get(key)
            if not isinstance(current_value, dict) or not isinstance(previous_value, dict):
                continue
            current_scores = current_value.get("scores")
            previous_scores = previous_value.get("scores")
            if not isinstance(current_scores, dict) or not isinstance(previous_scores, dict):
                continue
            for score_name, current_score in current_scores.items():
                previous_score = previous_scores.get(score_name)
                try:
                    current_number = float(current_score)
                    previous_number = float(previous_score)
                except (TypeError, ValueError):
                    continue
                if current_number < previous_number:
                    score_regressions.append({
                        "bucket": bucket_name,
                        "key": str(key),
                        "score": str(score_name),
                        "previous": previous_number,
                        "current": current_number,
                    })
    current_rules = {str(item) for item in current.get("rule_ids", []) if str(item).strip()}
    previous_rules = {str(item) for item in previous.get("rule_ids", []) if str(item).strip()}
    return {"score_regressions": score_regressions, "new_rule_ids": sorted(current_rules - previous_rules)}
