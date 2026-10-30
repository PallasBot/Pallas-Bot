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
STARTUP_DEADLINE_SEC = 60.0
RECONNECT_INITIAL_DELAY_SEC = 1.0
RECONNECT_MAX_DELAY_SEC = 10.0


class BridgeUnsupportedDeploymentError(RuntimeError):
    """Raised when the bridge is enabled on a deployment topology it cannot serve."""


class BridgeSendRefusedError(RuntimeError):
    """Raised when the controlled reply callback refuses to deliver a reply."""


_owner_config: MaiBotBridgeConfig | None = None
_bridge: MaiBotBridge | None = None
_connector_task: asyncio.Task[None] | None = None
_ready_event: asyncio.Event | None = None
_quiesced = False
_connected_once = False
_startup_failed = False

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
    return owner is not None and owner.owns_bot(int(bot_id)) and owner.owns_group(int(group_id))


def bridge_owns_account(bot_id: object) -> bool:
    """Whether a startup account is managed (used to filter peer-account traffic)."""
    owner = _owner_config
    return owner is not None and owner.owns_bot(bot_id)


def communication_allowed(bot_id: int, group_id: int) -> bool:
    """Live config and lifecycle state must still permit this owned scope."""
    if _quiesced or not bridge_owns(bot_id, group_id):
        return False
    live = _live_config_or_none()
    if live is None:
        return False
    return live.enabled and live.owns_bot(int(bot_id)) and int(group_id) in live.group_ids


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
    source = owner if owner is not None else live
    if owner is None:
        state = "disabled"
    elif _quiesced:
        state = "quiesced"
    elif _startup_failed:
        state = "startup_failed"
    elif _bridge is not None and _bridge.connected:
        state = "connected"
    elif _connected_once:
        state = "reconnecting"
    elif _connector_task is not None:
        state = "connecting"
    else:
        state = "connector_stopped"
    return {
        "enabled": live.enabled,
        "armed": owner is not None,
        "state": state,
        "connected": bool(_bridge is not None and _bridge.connected),
        "bot_id": owner.bot_id if owner is not None else live.bot_id,
        "bot_ids": sorted(source.bot_ids),
        "platform": source.platform,
        "group_ids": sorted(source.group_ids),
        "url_configured": bool(source.url),
    }


async def start_bridge() -> bool:
    """Arm the bridge after the send queue is ready.

    Raises ``BridgeConfigError`` for an explicitly enabled but invalid config and
    ``BridgeUnsupportedDeploymentError`` for a sharded deployment, instead of
    silently returning ``False``. Returns whether the bridge was armed.
    """
    global _bridge, _owner_config, _connector_task, _ready_event, _quiesced, _connected_once, _startup_failed
    if _owner_config is not None:
        return True
    config = load_bridge_config()
    if not config.enabled:
        return False
    from pallas.core.platform.shard import context as shard_ctx

    if shard_ctx.sharding_active():
        raise BridgeUnsupportedDeploymentError("MaiBot bridge does not support a sharded deployment")
    scope = BridgeScope(
        enabled=True,
        bot_ids=config.bot_ids,
        allowed_group_ids=config.group_ids,
        platform=config.platform,
    )
    bridge = MaiBotBridge(scope, bridge_send_reply)
    _owner_config = config
    _bridge = bridge
    _quiesced = False
    _connected_once = False
    _startup_failed = False
    _ready_event = asyncio.Event()
    _connector_task = asyncio.create_task(_connector_loop(bridge, config), name="maibot-bridge.connector")
    return True


async def _connector_loop(bridge: MaiBotBridge, config: MaiBotBridgeConfig) -> None:
    global _connector_task
    loop = asyncio.get_running_loop()
    deadline = loop.time() + STARTUP_DEADLINE_SEC
    delay = RECONNECT_INITIAL_DELAY_SEC
    try:
        while not _quiesced:
            remaining = deadline - loop.time()
            if not _connected_once and remaining <= 0:
                _mark_startup_failed()
                return
            connect_timeout = CONNECT_TIMEOUT_SEC if _connected_once else min(CONNECT_TIMEOUT_SEC, remaining)
            connected = await _wait_for_bridge_connection(bridge, config, connect_timeout)
            if connected:
                delay = RECONNECT_INITIAL_DELAY_SEC
            await bridge.close()
            if not _connected_once and loop.time() >= deadline:
                _mark_startup_failed()
                return
            if _quiesced:
                return
            sleep_for = delay if _connected_once else min(delay, max(0.0, deadline - loop.time()))
            if sleep_for:
                await asyncio.sleep(sleep_for)
            delay = min(delay * 2, RECONNECT_MAX_DELAY_SEC)
    except asyncio.CancelledError:
        return
    finally:
        await bridge.close()
        if _connector_task is asyncio.current_task():
            _connector_task = None


async def _wait_for_bridge_connection(bridge: MaiBotBridge, config: MaiBotBridgeConfig, connect_timeout: float) -> bool:
    global _connected_once
    connected = False
    try:
        await asyncio.wait_for(bridge.connect(config.url, config.token or None), timeout=connect_timeout)
        connected = True
        _connected_once = True
        if _ready_event is not None:
            _ready_event.set()
        await bridge.wait_closed()
        if _ready_event is not None:
            _ready_event.clear()
        log_rate_limited(
            logger,
            "warning",
            "maibot_bridge_disconnected",
            "MaiBot bridge connection closed; retrying while retaining scope ownership.",
            interval_sec=30.0,
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log_rate_limited(
            logger,
            "warning",
            "maibot_bridge_connect_failed",
            f"MaiBot bridge connection attempt failed ({type(exc).__name__}); scope remains owned.",
            interval_sec=30.0,
        )
    return connected


def _mark_startup_failed() -> None:
    global _startup_failed
    _startup_failed = True
    if _ready_event is not None:
        _ready_event.set()
    logger.error("MaiBot bridge startup deadline expired; scope stays owned without local fallback.")


async def wait_bridge_ready(timeout: float) -> bool:  # noqa: ASYNC109 - timeout is the public API contract
    """Wait for a current WebSocket connection, not a historical successful handshake."""
    if _bridge_available():
        return True
    ready = _ready_event
    if _owner_config is None or ready is None or _quiesced or _startup_failed:
        return False
    try:
        await asyncio.wait_for(ready.wait(), timeout=timeout)
    except TimeoutError:
        return False
    return _bridge_available()


async def quiesce_bridge() -> None:
    """Stop bridge communication while preserving fixed-scope ownership."""
    global _quiesced
    _quiesced = True
    if _ready_event is not None:
        _ready_event.set()
    bridge, task = _bridge, _connector_task
    if task is not None and task is not asyncio.current_task():
        if not task.done():
            task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            if asyncio.current_task().cancelling():
                raise
    if bridge is not None:
        await bridge.close()


async def stop_bridge() -> None:
    global _bridge, _owner_config, _connector_task, _ready_event, _quiesced, _connected_once, _startup_failed
    await quiesce_bridge()
    _bridge = None
    _owner_config = None
    _connector_task = None
    _ready_event = None
    _quiesced = False
    _connected_once = False
    _startup_failed = False


def _bridge_available(bridge: MaiBotBridge | None = None) -> bool:
    current = _bridge if bridge is None else bridge
    return not _quiesced and current is not None and current.connected


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
    if bridge_owns_account(getattr(event, "user_id", None)):
        return False  # never forward a managed peer account's own message
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
    if not _bridge_available(bridge) or not communication_allowed(bot_id, group_id):
        log_rate_limited(
            logger,
            "info",
            "maibot_bridge_offline",
            "MaiBot bridge is offline; scope-owned message captured only, no local fallback.",
            interval_sec=30.0,
        )
        return False
    try:
        alias_trigger = bool(getattr(event, "_pallas_llm_alias_hard_trigger", False))
        explicit_at = alias_trigger and any(
            getattr(segment, "type", None) == "at"
            and str(getattr(segment, "data", {}).get("qq", "")) == str(bot.self_id)
            for segment in (getattr(event, "original_message", None) or ())
        )
        await bridge.forward_event(
            onebot_event_dict(event),
            command_traffic=command_traffic,
            at_bot=bool(getattr(event, "to_me", False)) and (not alias_trigger or explicit_at),
            is_mentioned=alias_trigger,
        )
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
    if not _bridge_available():
        raise BridgeSendRefusedError("bridge is offline or quiesced")
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
    if not communication_allowed(int(bot_id), int(group_id)) or not _bridge_available():
        raise BridgeSendRefusedError("bridge became unavailable before reply delivery")
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
