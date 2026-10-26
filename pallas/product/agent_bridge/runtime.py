"""Live MaiBot bridge runtime: config cache, scope query, lifecycle, callback.

Ownership is a fixed snapshot taken when the bridge is armed: the bound bot and
its allowed groups come from the startup config, not from the live connection or
a later live edit. The live config is only consulted to *revoke* scope (disabled
or a group/bot removed); an invalid live config never releases scope back to the
old local agent. Static parameters and newly added groups/bots require a restart.
"""

from __future__ import annotations

import asyncio
from typing import Any

from nonebot import get_bot
from nonebot.log import logger

from pallas.core.foundation.config.repo_settings import repo_env_raw_value
from pallas.core.foundation.logging.throttle import log_rate_limited
from pallas.product.agent_bridge.config import (
    BRIDGE_KEYS,
    BridgeConfigError,
    MaiBotBridgeConfig,
    load_bridge_config,
    parse_bridge_config,
)
from pallas.product.agent_bridge.transport import (
    BridgeDisabledError,
    BridgeNotConnectedError,
    BridgeScope,
    MaiBotBridge,
)

CONNECT_TIMEOUT_SEC = 10.0


class BridgeUnsupportedDeploymentError(RuntimeError):
    """Raised when the bridge is enabled on a deployment topology it cannot serve."""


class BridgeSendRefusedError(RuntimeError):
    """Raised when the controlled reply callback refuses to deliver a reply."""


_owner_config: MaiBotBridgeConfig | None = None
_bridge: MaiBotBridge | None = None

_config_cache: MaiBotBridgeConfig | None = None
_config_cache_raw: tuple[object, ...] | None = None
_config_cache_valid = False
_invalid_config_logged = False


def clear_bridge_runtime_cache() -> None:
    global _config_cache, _config_cache_raw, _config_cache_valid, _invalid_config_logged
    _config_cache = None
    _config_cache_raw = None
    _config_cache_valid = False
    _invalid_config_logged = False


def _raw_bridge_values() -> tuple[object, ...]:
    return tuple(repo_env_raw_value(key) for key in BRIDGE_KEYS)


def _live_config_or_none() -> MaiBotBridgeConfig | None:
    """Live config, or ``None`` when it is explicitly enabled but invalid."""
    global _config_cache, _config_cache_raw, _config_cache_valid, _invalid_config_logged
    raw = _raw_bridge_values()
    if _config_cache_valid and _config_cache_raw == raw:
        return _config_cache
    try:
        config: MaiBotBridgeConfig | None = parse_bridge_config(dict(zip(BRIDGE_KEYS, raw, strict=True)))
    except BridgeConfigError as exc:
        if not _invalid_config_logged:
            _invalid_config_logged = True
            logger.error("MaiBot bridge live config invalid; scope is retained: {}", exc)
        config = None
    _config_cache = config
    _config_cache_raw = raw
    _config_cache_valid = True
    return config


def live_bridge_config() -> MaiBotBridgeConfig:
    return _live_config_or_none() or MaiBotBridgeConfig(enabled=False)


def bridge_owns(bot_id: int, group_id: int) -> bool:
    """Ownership from the fixed startup snapshot only; live edits never release it."""
    owner = _owner_config
    return owner is not None and owner.bot_id == int(bot_id) and owner.owns_group(int(group_id))


def communication_allowed(bot_id: int, group_id: int) -> bool:
    """Shared forward/reply admission: live config must still enable this bot+group."""
    if not bridge_owns(bot_id, group_id):
        return False
    live = _live_config_or_none()
    if live is None:
        return False
    return live.enabled and live.bot_id == int(bot_id) and int(group_id) in live.group_ids


def bridge_suppresses(bot_id: object, group_id: object) -> bool:
    """Tolerant ownership query for hot-path guards (old agent stays suppressed)."""
    try:
        bid = int(bot_id)  # type: ignore[arg-type]
        gid = int(group_id)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
    return bridge_owns(bid, gid)


def bridge_status() -> dict[str, Any]:
    live = live_bridge_config()
    owner = _owner_config
    return {
        "enabled": live.enabled,
        "armed": owner is not None,
        "connected": bool(_bridge is not None and _bridge.connected),
        "bot_id": owner.bot_id if owner is not None else live.bot_id,
        "platform": owner.platform if owner is not None else live.platform,
        "group_ids": sorted(owner.group_ids) if owner is not None else sorted(live.group_ids),
        "url_configured": bool(owner.url if owner is not None else live.url),
    }


async def start_bridge() -> bool:
    """Arm the bridge after the send queue is ready.

    Raises ``BridgeConfigError`` for an explicitly enabled but invalid config and
    ``BridgeUnsupportedDeploymentError`` for a sharded deployment, instead of
    silently returning ``False``. Returns whether the bridge was armed.
    """
    global _bridge, _owner_config
    config = load_bridge_config()
    if not config.enabled:
        _owner_config = None
        _bridge = None
        return False
    from pallas.core.platform.shard import context as shard_ctx

    if shard_ctx.sharding_active():
        raise BridgeUnsupportedDeploymentError("MaiBot bridge does not support a sharded deployment")
    scope = BridgeScope(
        enabled=True,
        bot_id=config.bot_id,
        allowed_group_ids=config.group_ids,
        platform=config.platform,
    )
    bridge = MaiBotBridge(scope, bridge_send_reply)
    _owner_config = config
    _bridge = bridge
    try:
        await asyncio.wait_for(bridge.connect(config.url, config.token or None), timeout=CONNECT_TIMEOUT_SEC)
    except Exception as exc:
        logger.error("MaiBot bridge connect failed; scope stays owned, no local fallback: {}", exc)
    return True


async def stop_bridge() -> None:
    global _bridge, _owner_config
    bridge = _bridge
    _bridge = None
    _owner_config = None
    if bridge is not None:
        await bridge.close()


async def group_ban_refusal(bot_id: int, group_id: int) -> str | None:
    """Group-level ACL ban check, matching packages/blacklist/gate_block.py."""
    from pallas.core.perm.acl import ACL_TARGET_GROUP_BAN, AclSubject, evaluate_acl

    decision = await evaluate_acl(
        action="event.receive",
        target=ACL_TARGET_GROUP_BAN,
        subject=AclSubject(group_id=int(group_id), bot_id=int(bot_id)),
    )
    if decision.source != "fallback":
        return None if decision.allow else "group_banned"
    from packages.blacklist.ban_gate import query_group_ban_status_for_gate

    if await query_group_ban_status_for_gate(int(group_id)):
        return "group_banned"
    return None


async def group_output_refusal(bot_id: int, group_id: int) -> str | None:
    """Shared group gate for forwarding and replies: switch, sleep, group ban."""
    from packages.help.plugin_manager import is_plugin_disabled
    from pallas.core.foundation.config import BotConfig

    if await is_plugin_disabled("llm_chat", int(group_id), int(bot_id)):
        return "chat_switch_off"
    if await BotConfig(int(bot_id), int(group_id)).is_sleep():
        return "sleeping"
    return await group_ban_refusal(int(bot_id), int(group_id))


def onebot_event_dict(event: Any) -> dict[str, Any]:
    """Serialise a real OneBot group event to the plain dict the transport parses."""
    return dict(event.model_dump(mode="json"))


async def forward_owned_event(bot: Any, event: Any, *, command_traffic: bool) -> bool:
    """Forward a scope-owned group message; never falls back to the old agent."""
    group_id = int(getattr(event, "group_id", 0) or 0)
    try:
        bot_id = int(bot.self_id)
    except (TypeError, ValueError):
        return False
    if not bridge_owns(bot_id, group_id):
        return False
    if not communication_allowed(bot_id, group_id):
        log_rate_limited(
            logger,
            "info",
            "maibot_bridge_forward_revoked",
            f"MaiBot bridge forward refused in group [{group_id}]: live config no longer enables it.",
            interval_sec=30.0,
        )
        return False
    if int(getattr(event, "user_id", 0) or 0) == bot_id:
        return False  # never forward the bound account's own message
    from pallas.product.message_scrub import is_message_scrub_blocked_async

    try:
        scrub_blocked = await is_message_scrub_blocked_async(
            plain_text=str(event.get_plaintext() or ""),
            raw_message=str(getattr(event, "raw_message", "") or ""),
            group_id=group_id,
            bot_id=bot_id,
        )
    except Exception:
        scrub_blocked = True  # fail closed on scrub errors
    if scrub_blocked:
        log_rate_limited(
            logger,
            "info",
            "maibot_bridge_forward_scrubbed",
            f"MaiBot bridge forward refused in group [{group_id}]: message review blocked it.",
            interval_sec=30.0,
        )
        return False
    reason = await group_output_refusal(bot_id, group_id)
    if reason is not None:
        log_rate_limited(
            logger,
            "info",
            "maibot_bridge_forward_gate",
            f"MaiBot bridge skipped forwarding in group [{group_id}]: {reason}.",
            interval_sec=30.0,
        )
        return False
    from pallas.core.perm.check import satisfies_command_permission

    if not await satisfies_command_permission(bot, event, "llm_chat.chat"):
        log_rate_limited(
            logger,
            "info",
            "maibot_bridge_forward_denied",
            "MaiBot bridge skipped forwarding a group message that failed the chat permission gate.",
            interval_sec=30.0,
        )
        return False
    bridge = _bridge
    if bridge is None or not bridge.connected:
        log_rate_limited(
            logger,
            "info",
            "maibot_bridge_offline",
            "MaiBot bridge is offline; scope-owned message captured only, no local fallback.",
            interval_sec=30.0,
        )
        return False
    try:
        await bridge.forward_event(onebot_event_dict(event), command_traffic=command_traffic)
    except BridgeNotConnectedError:
        log_rate_limited(
            logger,
            "info",
            "maibot_bridge_forward_disconnected",
            "MaiBot bridge disconnected while forwarding; captured only, no local fallback.",
            interval_sec=30.0,
        )
        return False
    except BridgeDisabledError:
        return False
    return True


async def bridge_send_reply(bot_id: int, group_id: int, text: str) -> int:
    """Controlled reply callback: re-check scope, group gate, scrub, then send."""
    from pallas.core.platform.ai_callback.delivery import send_group_message_with_receipt
    from pallas.product.message_scrub import is_message_scrub_blocked_async

    if not communication_allowed(int(bot_id), int(group_id)):
        raise BridgeSendRefusedError("bridge no longer owns this group")
    reason = await group_output_refusal(int(bot_id), int(group_id))
    if reason is not None:
        raise BridgeSendRefusedError(f"group output refused: {reason}")
    if await is_message_scrub_blocked_async(
        plain_text=text,
        raw_message=text,
        group_id=int(group_id),
        bot_id=int(bot_id),
    ):
        raise BridgeSendRefusedError("outgoing text blocked by message scrub")
    try:
        bot = get_bot(str(int(bot_id)))
    except ValueError as exc:
        raise BridgeSendRefusedError("bound bot is not connected") from exc

    from pallas.product.llm.sticker_followup import suppress_outgoing_sticker_followup

    try:
        with suppress_outgoing_sticker_followup():
            receipt = await send_group_message_with_receipt(bot, int(group_id), text)
    except Exception as exc:
        log_rate_limited(
            logger,
            "info",
            "maibot_bridge_send_error",
            f"MaiBot bridge reply send raised [{type(exc).__name__}]; refusing to echo.",
            interval_sec=30.0,
        )
        raise BridgeSendRefusedError(f"reply send failed: {type(exc).__name__}") from exc
    if not receipt.delivered or not receipt.message_id or receipt.message_id <= 0:
        log_rate_limited(
            logger,
            "info",
            "maibot_bridge_send_undelivered",
            "MaiBot bridge reply was not delivered with a real message id; refusing to echo.",
            interval_sec=30.0,
        )
        raise BridgeSendRefusedError("reply was not delivered with a real message id")
    return int(receipt.message_id)
