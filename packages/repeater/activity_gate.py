"""同群独占活动期间：限制复读主动发言与随意接话，保留跟复读。"""

from __future__ import annotations

from pallas.core.platform.ingress.hosted_activity_gate import loaded_hosted_activity_specs
from pallas.core.platform.shard.coord.hosted_activity_coord import coord_room_live
from pallas.product.ban_gate.snapshot import is_group_banned_fast


def group_has_hosted_activity(group_id: int) -> bool:
    gid = int(group_id)
    for spec in loaded_hosted_activity_specs():
        if coord_room_live(spec.activity_namespace, gid):
            return True
    return False


def group_is_banned(group_id: int) -> bool:
    """被全局拉黑的群禁止主动发言；快照未就绪时 fail-open（与入站门禁一致）。"""
    return is_group_banned_fast(int(group_id)) is True


def blocks_proactive_speak(group_id: int) -> bool:
    return group_is_banned(group_id) or group_has_hosted_activity(group_id)
