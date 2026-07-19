"""方舟知识库本地数据就绪检测。"""

from __future__ import annotations

from typing import Any

from pallas.core.domain.arknights.duel_sync import load_kb_operators_payload
from pallas.core.domain.arknights.sync import load_enemies_payload


def kb_sync_gaps() -> list[str]:
    """返回缺失项：operators / handbook / enemies。"""
    gaps: list[str] = []
    ops_payload = load_kb_operators_payload()
    if not _operators_ready(ops_payload):
        gaps.append("operators")
        return gaps
    if not _handbook_ready(ops_payload):
        gaps.append("handbook")
    if not _enemies_ready(load_enemies_payload()):
        gaps.append("enemies")
    return gaps


def kb_data_ready() -> bool:
    return not kb_sync_gaps()


def kb_status_snapshot() -> dict[str, Any]:
    ops_payload = load_kb_operators_payload()
    enemies_payload = load_enemies_payload()
    gaps = kb_sync_gaps()
    handbook_profiles = 0
    if isinstance(ops_payload, dict):
        handbook_profiles = int(ops_payload.get("handbook_profiles") or 0)
        if handbook_profiles <= 0:
            ops = ops_payload.get("operators")
            if isinstance(ops, list):
                handbook_profiles = sum(1 for op in ops if isinstance(op, dict) and op.get("handbook_lines"))
    return {
        "ready": not gaps,
        "gaps": gaps,
        "operators_count": int(ops_payload.get("count") or 0) if isinstance(ops_payload, dict) else 0,
        "rarity_filter": str(ops_payload.get("rarity_filter") or "") if isinstance(ops_payload, dict) else "",
        "handbook_enriched": bool(ops_payload.get("handbook_enriched")) if isinstance(ops_payload, dict) else False,
        "handbook_profiles": handbook_profiles,
        "enemies_count": int(enemies_payload.get("count") or 0) if isinstance(enemies_payload, dict) else 0,
        "data_source": str(ops_payload.get("source") or "") if isinstance(ops_payload, dict) else "",
    }


def _operators_ready(payload: dict[str, Any] | None) -> bool:
    if not isinstance(payload, dict):
        return False
    count = int(payload.get("count") or 0)
    if count <= 0:
        return False
    ops = payload.get("operators")
    return isinstance(ops, list) and len(ops) > 0


def _handbook_ready(payload: dict[str, Any] | None) -> bool:
    if not isinstance(payload, dict):
        return False
    if not payload.get("handbook_enriched"):
        return False
    profiles = int(payload.get("handbook_profiles") or 0)
    if profiles > 0:
        return True
    ops = payload.get("operators")
    if not isinstance(ops, list):
        return False
    return any(isinstance(op, dict) and op.get("handbook_lines") for op in ops)


def _enemies_ready(payload: dict[str, Any] | None) -> bool:
    if not isinstance(payload, dict):
        return False
    count = int(payload.get("count") or 0)
    if count <= 0:
        return False
    enemies = payload.get("enemies")
    return isinstance(enemies, list) and len(enemies) > 0
