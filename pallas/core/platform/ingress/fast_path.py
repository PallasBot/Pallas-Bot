from __future__ import annotations

from pallas.core.foundation.command_prefix import matches_command_prefix
from pallas.core.platform.ingress.dream_host_gate import DREAM_HOST_GATE_PLUGIN
from pallas.core.platform.ingress.hosted_activity_gate import (
    loaded_hosted_activity_specs,
    spec_matches_in_room_command,
    spec_matches_speak_traffic,
)
from pallas.core.platform.multi_bot.dedup import needs_group_host_bot_gate
from pallas.core.platform.shard.coord.group_gate import read_owned_gate_bot_id_sync
from pallas.core.platform.shard.coord.hosted_activity_coord import hosted_activity_live


def ingress_once_claim_safe_before_host_gates(
    group_id: int,
    plain: str,
    *,
    at_fleet_bot: bool,
) -> bool:
    if not needs_group_host_bot_gate():
        return True

    gid = int(group_id)
    text = (plain or "").strip()
    for spec in loaded_hosted_activity_specs():
        in_room = spec_matches_in_room_command(spec, plain)
        speak = spec_matches_speak_traffic(spec, gid, plain, at_fleet_bot=at_fleet_bot)
        open_or_end = any(matches_command_prefix(text, prefix) for prefix in spec.always_pass_prefixes)
        if not in_room and not speak and not open_or_end:
            continue
        if hosted_activity_live(
            activity_namespace=spec.activity_namespace,
            plugin_key=spec.plugin_key,
            group_id=gid,
        ):
            return False

    if read_owned_gate_bot_id_sync(DREAM_HOST_GATE_PLUGIN, gid) is not None:
        return False
    return True
