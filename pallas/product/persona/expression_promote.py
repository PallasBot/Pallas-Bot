"""Review and automatically activate learned group expressions."""

from __future__ import annotations

from typing import Literal

from pallas.core.foundation.fs_lock import interprocess_file_lock
from pallas.product.llm.config import get_llm_config
from pallas.product.persona.expression_bank import (
    ExpressionEntry,
    _load_expression_entries,
    _write_expression_entries,
    expression_entries_path,
    list_group_expressions,
)

AUTO_SUPPORT_THRESHOLD = 3
ResolveAction = Literal["approve", "reject"]


def is_expression_auto_eligible(entry: ExpressionEntry) -> bool:
    return entry.status == "shadow" and entry.source == "llm_success" and int(entry.support) >= AUTO_SUPPORT_THRESHOLD


def list_expression_candidates(
    group_id: int,
    *,
    limit: int = 50,
    include_resolved: bool = False,
) -> list[ExpressionEntry]:
    rows = list_group_expressions(int(group_id), limit=limit)
    if include_resolved:
        return rows
    return [entry for entry in rows if entry.status == "shadow"]


def list_pending_expressions(group_id: int, *, limit: int = 50) -> list[ExpressionEntry]:
    return list_expression_candidates(group_id, limit=limit)


def resolve_expression(
    entry_id: str,
    *,
    action: ResolveAction,
    reason: str = "",
) -> ExpressionEntry | None:
    target_id = str(entry_id or "").strip()
    if not target_id or action not in ("approve", "reject"):
        return None
    path = expression_entries_path()
    with interprocess_file_lock(path.with_suffix(path.suffix + ".lock")):
        rows = _load_expression_entries()
        for index, entry in enumerate(rows):
            if entry.entry_id != target_id:
                continue
            if action == "approve":
                updated = entry.model_copy(update={"status": "active", "rejected_reason": ""})
            else:
                rejected_reason = str(reason or "rejected").strip() or "rejected"
                updated = entry.model_copy(update={"status": "rejected", "rejected_reason": rejected_reason})
            rows[index] = updated
            _write_expression_entries(path, rows)
            return updated
    return None


def maybe_auto_promote_for_group(group_id: int) -> list[ExpressionEntry]:
    if not bool(getattr(get_llm_config(), "llm_expression_auto_promote_enabled", False)):
        return []
    promoted: list[ExpressionEntry] = []
    for entry in list_pending_expressions(int(group_id), limit=200):
        if not is_expression_auto_eligible(entry):
            continue
        updated = resolve_expression(entry.entry_id, action="approve")
        if updated is not None:
            promoted.append(updated)
    return promoted
