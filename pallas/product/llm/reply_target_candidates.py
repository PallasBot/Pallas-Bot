"""Recent group messages eligible for native quote replies."""

from __future__ import annotations

from collections import defaultdict, deque

from pallas.product.llm.current_turn_decision import ReplyTargetCandidate

_MAX_CANDIDATES_PER_GROUP = 6
_RECENT_REPLY_TARGETS: dict[int, deque[ReplyTargetCandidate]] = defaultdict(
    lambda: deque(maxlen=_MAX_CANDIDATES_PER_GROUP)
)


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
