"""决斗扩展协调桥接。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pallas.core.plugin_coord._lazy import import_symbol_any

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

_get_duel_pair: Callable[[int], Awaitable[tuple[int, int] | None]] | None = None
_should_skip_repeater_learn: Callable[[int, int, str], Awaitable[bool]] | None = None
_is_duel_paired_bot_traffic: Callable[[int, int, int], Awaitable[bool]] | None = None
_duel_qte_blocks_greeting_user: Callable[[int, str | int], bool] | None = None
_bot_qte_success_rate: Callable[[str], float] | None = None
_pick_bot_wrong_qte_reply: Callable[..., str | None] | None = None
_apply_cluster_qte_greeting: Callable[[str, frozenset[str] | None, float], None] | None = None
_reload_operators_cache: Callable[[], Any] | None = None


def register_duel_coord(
    *,
    get_duel_pair: Callable[[int], Awaitable[tuple[int, int] | None]] | None = None,
    should_skip_repeater_learn: Callable[[int, int, str], Awaitable[bool]] | None = None,
    is_duel_paired_bot_traffic: Callable[[int, int, int], Awaitable[bool]] | None = None,
    duel_qte_blocks_greeting_user: Callable[[int, str | int], bool] | None = None,
    bot_qte_success_rate: Callable[[str], float] | None = None,
    pick_bot_wrong_qte_reply: Callable[..., str | None] | None = None,
    apply_cluster_qte_greeting: Callable[[str, frozenset[str] | None, float], None] | None = None,
    reload_operators_cache: Callable[[], Any] | None = None,
) -> None:
    g = globals()
    if get_duel_pair is not None:
        g["_get_duel_pair"] = get_duel_pair
    if should_skip_repeater_learn is not None:
        g["_should_skip_repeater_learn"] = should_skip_repeater_learn
    if is_duel_paired_bot_traffic is not None:
        g["_is_duel_paired_bot_traffic"] = is_duel_paired_bot_traffic
    if duel_qte_blocks_greeting_user is not None:
        g["_duel_qte_blocks_greeting_user"] = duel_qte_blocks_greeting_user
    if bot_qte_success_rate is not None:
        g["_bot_qte_success_rate"] = bot_qte_success_rate
    if pick_bot_wrong_qte_reply is not None:
        g["_pick_bot_wrong_qte_reply"] = pick_bot_wrong_qte_reply
    if apply_cluster_qte_greeting is not None:
        g["_apply_cluster_qte_greeting"] = apply_cluster_qte_greeting
    if reload_operators_cache is not None:
        g["_reload_operators_cache"] = reload_operators_cache


_DUEL_SESSION = ("pallas_plugin_duel.duel_session", "packages.duel.duel_session")
_DUEL_QTE = ("pallas_plugin_duel.duel_qte", "packages.duel.duel_qte")
_DUEL_OPS = ("pallas_plugin_duel.arknights_ops", "packages.duel.arknights_ops")


async def get_duel_pair(group_id: int) -> tuple[int, int] | None:
    if _get_duel_pair is not None:
        return await _get_duel_pair(group_id)
    fn = import_symbol_any(_DUEL_SESSION, "get_duel_pair")
    if fn is None:
        return None
    return await fn(group_id)


async def should_skip_repeater_learn(group_id: int, user_id: int, raw_message: str) -> bool:
    if _should_skip_repeater_learn is not None:
        return await _should_skip_repeater_learn(group_id, user_id, raw_message)
    fn = import_symbol_any(_DUEL_SESSION, "should_skip_repeater_learn")
    if fn is None:
        return False
    return bool(await fn(group_id, user_id, raw_message))


async def is_duel_paired_bot_traffic(group_id: int, sender_id: int, receiver_bot_id: int) -> bool:
    if _is_duel_paired_bot_traffic is not None:
        return await _is_duel_paired_bot_traffic(group_id, sender_id, receiver_bot_id)
    fn = import_symbol_any(_DUEL_SESSION, "is_duel_paired_bot_traffic")
    if fn is None:
        return False
    return bool(await fn(group_id, sender_id, receiver_bot_id))


def duel_qte_blocks_greeting_user(group_id: int, user_id: str | int) -> bool:
    if _duel_qte_blocks_greeting_user is not None:
        return _duel_qte_blocks_greeting_user(group_id, user_id)
    fn = import_symbol_any(_DUEL_QTE, "duel_qte_blocks_greeting_user")
    if fn is None:
        return False
    return bool(fn(group_id, user_id))


def bot_qte_success_rate(qte_kind: str) -> float:
    if _bot_qte_success_rate is not None:
        return float(_bot_qte_success_rate(qte_kind))
    fn = import_symbol_any(_DUEL_QTE, "bot_qte_success_rate")
    if fn is None:
        return 0.0
    return float(fn(qte_kind))


def pick_bot_wrong_qte_reply(
    correct: str,
    qte_kind: str,
    *,
    decoy_keys: list[str] | None = None,
) -> str | None:
    if _pick_bot_wrong_qte_reply is not None:
        return _pick_bot_wrong_qte_reply(correct, qte_kind, decoy_keys=decoy_keys)
    fn = import_symbol_any(_DUEL_QTE, "pick_bot_wrong_qte_reply")
    if fn is None:
        return None
    return fn(correct, qte_kind, decoy_keys=decoy_keys)


def apply_cluster_qte_greeting(gid: str, users: frozenset[str] | None, deadline: float) -> None:
    if _apply_cluster_qte_greeting is not None:
        _apply_cluster_qte_greeting(gid, users, deadline)
        return
    fn = import_symbol_any(_DUEL_QTE, "apply_cluster_qte_greeting")
    if fn is not None:
        fn(gid, users, deadline)


def reload_operators_cache() -> Any:
    if _reload_operators_cache is not None:
        return _reload_operators_cache()
    fn = import_symbol_any(_DUEL_OPS, "reload_operators_cache")
    if fn is None:
        return None
    return fn()
