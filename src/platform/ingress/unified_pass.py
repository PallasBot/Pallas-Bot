"""unified 模式下 ingress_gate once claim 胜出标记，供 repeater / 口令 matcher 跳过二次抢占。"""

from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING

from src.platform.multi_bot.dedup import cross_bot_message_signature

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import GroupMessageEvent

_PASS_MAX = 8000
_pass_keys: set[tuple[int, int, str, int]] = set()
_pass_order: deque[tuple[int, int, str, int]] = deque()


def reset_unified_ingress_once_pass_for_tests() -> None:
    _pass_keys.clear()
    _pass_order.clear()


def unified_ingress_once_signature(
    group_id: int,
    user_id: int,
    body: str,
    message_time: int,
) -> tuple[int, int, str, int]:
    sig = cross_bot_message_signature(
        group_id,
        user_id,
        body,
        message_time,
        use_plaintext=True,
        include_message_time=True,
    )
    return (int(group_id), int(user_id), str(sig[2]), int(sig[3]))


def mark_unified_ingress_once_won(
    event: GroupMessageEvent,
    *,
    body: str,
) -> None:
    sig = unified_ingress_once_signature(
        int(event.group_id),
        int(event.user_id),
        body,
        int(event.time),
    )
    if sig in _pass_keys:
        return
    _pass_keys.add(sig)
    _pass_order.append(sig)
    while len(_pass_order) > _PASS_MAX:
        old = _pass_order.popleft()
        _pass_keys.discard(old)


def unified_ingress_once_won(
    event: GroupMessageEvent,
    *,
    plain: str | None = None,
    body: str | None = None,
) -> bool:
    plain_body = (plain if plain is not None else event.get_plaintext() or "").strip()
    msg_body = body if body is not None else (plain_body or event.raw_message)
    sig = unified_ingress_once_signature(
        int(event.group_id),
        int(event.user_id),
        msg_body,
        int(event.time),
    )
    return sig in _pass_keys


def unified_ingress_once_won_for_text(
    group_id: int,
    user_id: int,
    plain_text: str,
    message_time: int,
) -> bool:
    body = (plain_text or "").strip() or plain_text or ""
    sig = unified_ingress_once_signature(group_id, user_id, body, message_time)
    return sig in _pass_keys
