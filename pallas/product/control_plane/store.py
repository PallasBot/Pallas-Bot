"""bootstrap 落盘：写入 community_stats.json，供 federate / coord 读取。"""

from __future__ import annotations

import time
from typing import Any

from pallas.product.community_stats.store import _read_state_raw, _write_state


def load_bootstrap_coord() -> dict[str, Any] | None:
    raw = _read_state_raw().get("control_plane_bootstrap")
    if not isinstance(raw, dict):
        return None
    coord = raw.get("coord")
    return coord if isinstance(coord, dict) else None


def load_bootstrap_coord_redis_url() -> str:
    coord = load_bootstrap_coord()
    if not coord:
        return ""
    return str(coord.get("redis_url") or "").strip()


def load_bootstrap_coord_redis_prefix() -> str:
    coord = load_bootstrap_coord()
    if not coord:
        return ""
    return str(coord.get("redis_prefix") or "").strip()


def load_bootstrap_corpus_community() -> dict[str, Any] | None:
    raw = _read_state_raw().get("control_plane_bootstrap")
    if not isinstance(raw, dict):
        return None
    block = raw.get("corpus_community")
    return dict(block) if isinstance(block, dict) else None


def load_bootstrap_claim_ttl_sec() -> int | None:
    coord = load_bootstrap_coord()
    if not coord or coord.get("claim_ttl_sec") is None:
        return None
    try:
        return max(60, int(coord.get("claim_ttl_sec")))
    except (TypeError, ValueError):
        return None


def bootstrap_state_valid(*, skew_sec: int = 120) -> bool:
    raw = _read_state_raw().get("control_plane_bootstrap")
    if not isinstance(raw, dict):
        return False
    expires = raw.get("expires_at")
    if expires is None:
        return bool(raw.get("fetched_at"))
    try:
        return int(expires) > int(time.time()) - skew_sec
    except (TypeError, ValueError):
        return False


def save_bootstrap_payload(
    *,
    federate_id: str = "",
    coord: dict[str, Any] | None = None,
    corpus_community: dict[str, Any] | None = None,
    expires_at: int | None = None,
) -> None:
    data = dict(_read_state_raw())
    fid = (federate_id or "").strip()
    if fid:
        data["federate_id"] = fid
    entry: dict[str, Any] = {
        "fetched_at": int(time.time()),
        "expires_at": expires_at,
    }
    if coord:
        entry["coord"] = coord
    if corpus_community:
        entry["corpus_community"] = corpus_community
    data["control_plane_bootstrap"] = entry
    _write_state(data)
