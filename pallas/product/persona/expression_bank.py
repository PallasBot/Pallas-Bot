"""Persistent per-group expression bank entries."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from pallas.core.foundation.paths import plugin_data_dir
from pallas.product.persona.occasion import normalize_occasion_tag

ExpressionSource = Literal["group_observe", "llm_success"]
ExpressionStatus = Literal["shadow", "active", "rejected"]
ExpressionKey = tuple[str, str]


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


def expression_bank_base_dir() -> Path:
    env_dir = str(os.environ.get("PALLAS_DATA_DIR") or "").strip()
    if env_dir:
        root = Path(env_dir)
        root.mkdir(parents=True, exist_ok=True)
        path = root / "expression_bank"
    else:
        path = plugin_data_dir("pb_webui", create=True) / "expression_bank"
    path.mkdir(parents=True, exist_ok=True)
    return path


def expression_entries_path() -> Path:
    return expression_bank_base_dir() / "entries.jsonl"


def normalize_expression_key(occasion: str, saying: str) -> ExpressionKey:
    return (
        normalize_occasion_tag(occasion)[:20].strip(),
        str(saying or "").strip()[:20].strip(),
    )


def build_entry_id(group_id: int, key: ExpressionKey) -> str:
    occasion, saying = normalize_expression_key(*key)
    digest = hashlib.sha256(f"{int(group_id)}\n{occasion}\n{saying}".encode()).hexdigest()[:12]
    return f"expr-{int(group_id)}-{digest}"


def _iter_expression_entries(path: Path):
    with path.open(encoding="utf-8", errors="replace") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            try:
                yield ExpressionEntry.model_validate(json.loads(line))
            except (TypeError, ValueError):
                continue


def _load_expression_entries() -> list[ExpressionEntry]:
    path = expression_entries_path()
    if not path.exists():
        return []
    return list(_iter_expression_entries(path))


def _write_expression_entries(path: Path, rows: list[ExpressionEntry]) -> None:
    from pallas.core.foundation.fs_lock import atomic_write_text

    body = "".join(json.dumps(item.model_dump(mode="json"), ensure_ascii=False) + "\n" for item in rows)
    atomic_write_text(path, body)


def append_or_merge_expression(entry: ExpressionEntry) -> ExpressionEntry:
    """Store an entry, merging support for the same group and normalized key."""
    from pallas.core.foundation.fs_lock import interprocess_file_lock

    key = normalize_expression_key(entry.occasion, entry.saying)
    canonical_entry = entry.model_copy(
        update={
            "entry_id": build_entry_id(entry.group_id, key),
            "occasion": key[0],
            "saying": key[1],
            "support": max(1, int(entry.support)),
        }
    )
    path = expression_entries_path()
    with interprocess_file_lock(path.with_suffix(path.suffix + ".lock")):
        rows = _load_expression_entries()
        for index, current in enumerate(rows):
            if current.group_id != canonical_entry.group_id:
                continue
            if normalize_expression_key(current.occasion, current.saying) != key:
                continue
            incoming_source = canonical_entry.source
            source = "llm_success" if "llm_success" in {current.source, incoming_source} else "group_observe"
            status = current.status if current.status == "rejected" else canonical_entry.status
            merged = current.model_copy(
                update={
                    "support": max(1, int(current.support)) + canonical_entry.support,
                    "source": source,
                    "status": status,
                    "updated_at": max(current.updated_at, canonical_entry.updated_at),
                }
            )
            rows[index] = merged
            _write_expression_entries(path, rows)
            return merged
        rows.append(canonical_entry)
        _write_expression_entries(path, rows)
    return canonical_entry


def record_expression_outcome(entry_ids: list[str], *, scene: str, score_delta: int, outcome_id: str) -> None:
    targets = {str(item).strip() for item in entry_ids if str(item).strip()}
    if not targets:
        return
    path = expression_entries_path()
    from pallas.core.foundation.fs_lock import interprocess_file_lock

    with interprocess_file_lock(path.with_suffix(path.suffix + ".lock")):
        rows = _load_expression_entries()
        changed = False
        for index, row in enumerate(rows):
            if row.entry_id not in targets or outcome_id in row.applied_outcome_ids:
                continue
            feedback = {key: dict(value) for key, value in row.scene_feedback.items()}
            stat = feedback.setdefault(normalize_occasion_tag(scene), {"uses": 0, "score": 0})
            stat["uses"] = int(stat.get("uses", 0)) + 1
            stat["score"] = int(stat.get("score", 0)) + int(score_delta)
            rows[index] = row.model_copy(
                update={"scene_feedback": feedback, "applied_outcome_ids": [*row.applied_outcome_ids, outcome_id]}
            )
            changed = True
        if changed:
            _write_expression_entries(path, rows)


def list_group_expressions(
    group_id: int,
    *,
    status: ExpressionStatus | None = None,
    limit: int = 50,
) -> list[ExpressionEntry]:
    target_group_id = int(group_id)
    rows = [
        item
        for item in _load_expression_entries()
        if item.group_id == target_group_id and (status is None or item.status == status)
    ]
    return rows[-max(1, int(limit)) :]
