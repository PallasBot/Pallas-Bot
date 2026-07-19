"""社区语料 enroll 落盘。"""

from __future__ import annotations

import time
from typing import Any

from pallas.product.community_stats.store import _read_state_raw, _write_state


def load_corpus_community_state() -> dict[str, Any]:
    raw = _read_state_raw().get("corpus_community")
    return dict(raw) if isinstance(raw, dict) else {}


def save_corpus_community_state(
    *,
    api_base: str,
    corpus_token: str,
    expires_at: int | None = None,
    contribute: bool | None = None,
) -> None:
    data = _read_state_raw()
    block: dict[str, Any] = {
        "api_base": (api_base or "").strip().rstrip("/"),
        "corpus_token": (corpus_token or "").strip(),
        "enrolled_at": int(time.time()),
    }
    if expires_at is not None:
        block["expires_at"] = int(expires_at)
    if contribute is not None:
        block["contribute"] = bool(contribute)
    data["corpus_community"] = block
    _write_state(data)


def corpus_community_enrollment_valid(state: dict[str, Any] | None = None) -> bool:
    block = state if state is not None else load_corpus_community_state()
    token = str(block.get("corpus_token") or "").strip()
    api_base = str(block.get("api_base") or "").strip()
    if not token or not api_base:
        return False
    expires = block.get("expires_at")
    if expires is not None and int(expires) < int(time.time()):
        return False
    return True
