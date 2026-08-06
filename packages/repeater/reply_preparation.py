"""复读接话的同步准备：决定是否查询候选并保留 fanout 归属。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .bundle_lookup import find_reply_bundle_bounded
from .fanout_reply import FanoutGate, repeater_can_attempt_reply, resolve_fanout_gate
from .reply_gate import should_prepare_repeater_reply

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import GroupMessageEvent

    from .model import Chat


@dataclass(frozen=True, slots=True)
class PreparedRepeaterReply:
    bundle: Any | None
    fanout_gate: FanoutGate | None = None


async def prepare_repeater_reply(
    event: GroupMessageEvent,
    chat: Chat,
    *,
    plain_body: str,
    sharding_active: bool,
) -> PreparedRepeaterReply:
    bot_id = int(event.self_id)
    group_id = int(event.group_id)
    if not await repeater_can_attempt_reply(bot_id, group_id):
        return PreparedRepeaterReply(bundle=None)
    if not should_prepare_repeater_reply(plain_body, sharding_active=sharding_active):
        return PreparedRepeaterReply(bundle=None)

    fanout_gate = await resolve_fanout_gate(event)
    if fanout_gate.lost:
        return PreparedRepeaterReply(bundle=None, fanout_gate=fanout_gate)
    return PreparedRepeaterReply(
        bundle=await find_reply_bundle_bounded(chat),
        fanout_gate=fanout_gate,
    )
