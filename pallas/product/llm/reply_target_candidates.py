"""Recent group messages eligible for native quote replies."""

from __future__ import annotations

import random
import threading
import time
from collections import defaultdict, deque

from pallas.product.llm.current_turn_decision import ReplyTargetCandidate

_MAX_CANDIDATES_PER_GROUP = 6
_RECENT_REPLY_TARGETS: dict[int, deque[ReplyTargetCandidate]] = defaultdict(
    lambda: deque(maxlen=_MAX_CANDIDATES_PER_GROUP)
)

_QUOTE_COOLDOWN_SEC = 120
_QUOTE_LOCK = threading.Lock()
_LAST_QUOTE_AT: dict[int, float] = {}


def record_reply_target_candidate(
    *,
    group_id: int,
    message_id: int,
    sender_id: int,
    text: str,
) -> None:
    clean = str(text or "").strip()[:160]
    if int(group_id) <= 0 or int(message_id) <= 0 or not clean:
        return
    candidate = ReplyTargetCandidate(
        message_id=int(message_id),
        sender_id=int(sender_id) if sender_id is not None else 0,
        text=clean,
    )
    entries = _RECENT_REPLY_TARGETS[int(group_id)]
    if any(item.message_id == candidate.message_id for item in entries):
        return
    entries.append(candidate)


def list_reply_target_candidates(
    *,
    group_id: int,
    current_message_id: int | None = None,
) -> list[ReplyTargetCandidate]:
    current_id = int(current_message_id) if current_message_id else 0
    return [
        item.model_copy(update={"is_current": item.message_id == current_id})
        for item in _RECENT_REPLY_TARGETS.get(int(group_id), ())
    ]


def clear_reply_target_candidates() -> None:
    _RECENT_REPLY_TARGETS.clear()


_QUOTE_EMIT_PROBABILITY = 0.25


def should_emit_quote(
    group_id: int | None,
    *,
    rng: random.Random | None = None,
    now: float | None = None,
) -> bool:
    """Whether a reply-to-candidate may be delivered as a native quote."""
    rng = rng or random.Random()
    if group_id is None or int(group_id) <= 0:
        return False
    ts = now if now is not None else time.time()
    with _QUOTE_LOCK:
        last = _LAST_QUOTE_AT.get(int(group_id))
        if last is not None and (ts - last) < _QUOTE_COOLDOWN_SEC:
            return False
    return rng.random() < _QUOTE_EMIT_PROBABILITY


def note_quote_emitted(group_id: int | None, *, now: float | None = None) -> None:
    """Record that a native quote was delivered for cooldown purposes."""
    if group_id is None or int(group_id) <= 0:
        return
    with _QUOTE_LOCK:
        _LAST_QUOTE_AT[int(group_id)] = now if now is not None else time.time()
