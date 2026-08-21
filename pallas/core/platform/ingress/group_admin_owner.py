"""Ingress policy for commands requiring a locally capable group-admin Bot."""

from __future__ import annotations

from dataclasses import dataclass

from nonebot import logger

from pallas.core.platform.federate.peer_bots import (
    GroupAdminOwner,
    federate_group_admin_owner,
)
from pallas.core.platform.ingress.route_index import (
    get_route_index,
    resolve_message_route,
)
from pallas.core.platform.multi_bot.group_admin_capability import (
    warm_local_group_admin_observations,
)
from pallas.core.platform.multi_bot.group_online_cache import (
    resolve_local_connected_bots_in_group,
)

GROUP_ADMIN_CAPABILITY = "group_admin"
_logged_unknown_capabilities: set[str] = set()


@dataclass(frozen=True)
class GroupAdminOwnerIngressDecision:
    passes: bool
    fallback_to_fanout: bool = False


def group_admin_owner_ingress_route(*, passive: bool = True) -> dict[str, object]:
    return {
        "passive": passive,
        "required_bot_capability": GROUP_ADMIN_CAPABILITY,
    }


def required_bot_capability_for_plain(plain: str) -> str | None:
    resolution = resolve_message_route(plain)
    index = get_route_index()
    capabilities = {
        index.required_bot_capabilities[module]
        for module in resolution.matched_modules
        if module in index.required_bot_capabilities
    }
    if not capabilities:
        return None
    if capabilities == {GROUP_ADMIN_CAPABILITY}:
        return GROUP_ADMIN_CAPABILITY
    for capability in sorted(capabilities):
        if capability not in _logged_unknown_capabilities:
            _logged_unknown_capabilities.add(capability)
            logger.debug("Unknown required Bot capability [{}] in ingress route", capability)
    return None


def group_admin_owner_for_plain(plain: str, group_id: int) -> GroupAdminOwner | None:
    if required_bot_capability_for_plain(plain) != GROUP_ADMIN_CAPABILITY:
        return None
    return federate_group_admin_owner(group_id, plain=plain)


async def group_admin_owner_ingress_passes(
    group_id: int,
    bot_id: int,
    plain: str,
) -> bool:
    return (await group_admin_owner_ingress_decision(group_id, bot_id, plain)).passes


async def group_admin_owner_ingress_decision(
    group_id: int,
    bot_id: int,
    plain: str,
) -> GroupAdminOwnerIngressDecision:
    if required_bot_capability_for_plain(plain) != GROUP_ADMIN_CAPABILITY:
        return GroupAdminOwnerIngressDecision(passes=True)

    local_bot_ids = await resolve_local_connected_bots_in_group(group_id, force_probe=True)
    await warm_local_group_admin_observations(group_id, local_bot_ids)
    owner = group_admin_owner_for_plain(plain, group_id)
    if owner is None:
        return GroupAdminOwnerIngressDecision(passes=True, fallback_to_fanout=True)
    return GroupAdminOwnerIngressDecision(
        passes=owner.deployment_id == _local_deployment_id() and owner.bot_id == int(bot_id)
    )


def _local_deployment_id() -> str:
    from pallas.product.community_stats.store import load_or_create_deployment_id

    return load_or_create_deployment_id().strip().lower()
