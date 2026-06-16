"""同群独占活动期间：限制复读主动发言与随意接话，保留跟复读。"""

from __future__ import annotations

from src.platform.ingress.hosted_activity_gate import loaded_hosted_activity_specs
from src.platform.shard.coord.hosted_activity_coord import coord_room_live


def group_has_hosted_activity(group_id: int) -> bool:
    gid = int(group_id)
    for spec in loaded_hosted_activity_specs():
        if coord_room_live(spec.activity_namespace, gid):
            return True
    return False


def blocks_proactive_speak(group_id: int) -> bool:
    return group_has_hosted_activity(group_id)
