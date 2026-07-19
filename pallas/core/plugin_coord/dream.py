"""做梦扩展协调桥接。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pallas.core.plugin_coord._lazy import import_symbol_any

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

_drift_payload_to_dict: Callable[[Any], dict[str, Any]] | None = None
_drift_payload_from_dict: Callable[[dict[str, Any]], Any] | None = None
_deliver_drift_payload: Callable[[int, int, Any], Awaitable[bool]] | None = None


def register_dream_coord(
    *,
    drift_payload_to_dict: Callable[[Any], dict[str, Any]] | None = None,
    drift_payload_from_dict: Callable[[dict[str, Any]], Any] | None = None,
    deliver_drift_payload: Callable[[int, int, Any], Awaitable[bool]] | None = None,
) -> None:
    g = globals()
    if drift_payload_to_dict is not None:
        g["_drift_payload_to_dict"] = drift_payload_to_dict
    if drift_payload_from_dict is not None:
        g["_drift_payload_from_dict"] = drift_payload_from_dict
    if deliver_drift_payload is not None:
        g["_deliver_drift_payload"] = deliver_drift_payload


_DREAM_PAYLOAD = ("pallas_plugin_dream.payload", "packages.dream.payload")
_DREAM_RUNTIME = ("pallas_plugin_dream.runtime", "packages.dream.runtime")


def drift_payload_to_dict(payload: Any) -> dict[str, Any]:
    if _drift_payload_to_dict is not None:
        return _drift_payload_to_dict(payload)
    fn = import_symbol_any(_DREAM_PAYLOAD, "drift_payload_to_dict")
    if fn is None:
        raise RuntimeError("dream plugin not available")
    return fn(payload)


def drift_payload_from_dict(data: dict[str, Any]) -> Any:
    if _drift_payload_from_dict is not None:
        return _drift_payload_from_dict(data)
    fn = import_symbol_any(_DREAM_PAYLOAD, "drift_payload_from_dict")
    if fn is None:
        raise RuntimeError("dream plugin not available")
    return fn(data)


async def deliver_drift_payload(bot_id: int, target_group_id: int, payload: Any) -> bool:
    if _deliver_drift_payload is not None:
        return bool(await _deliver_drift_payload(bot_id, target_group_id, payload))
    fn = import_symbol_any(_DREAM_RUNTIME, "deliver_drift_payload")
    if fn is None:
        return False
    return bool(await fn(bot_id, target_group_id, payload))


async def stop_dream_worker(bot_id: int, group_id: int) -> None:
    fn = import_symbol_any(_DREAM_RUNTIME, "stop_dream_worker")
    if fn is None:
        return
    await fn(bot_id, group_id)


async def send_dream_wake_text(bot_id: int, group_id: int) -> None:
    fn = import_symbol_any(_DREAM_RUNTIME, "send_dream_wake_text")
    if fn is None:
        return
    await fn(bot_id, group_id)
