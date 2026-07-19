"""跨部署多机协同。"""

from .config import (
    clear_federate_config_cache,
    federate_ingress_active,
    federate_redis_available,
    get_federate_config,
    resolved_federate_id,
)
from .dedup import try_claim_cross_federate_message
from .ingress import claim_federate_group_message_ingress
from .peer_bots import federate_peer_bot_ids_contains, get_federate_peer_bot_ids

__all__ = [
    "claim_federate_group_message_ingress",
    "clear_federate_config_cache",
    "federate_peer_bot_ids_contains",
    "federate_ingress_active",
    "federate_redis_available",
    "get_federate_peer_bot_ids",
    "get_federate_config",
    "resolved_federate_id",
    "try_claim_cross_federate_message",
]
