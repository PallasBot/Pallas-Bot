"""分片 worker coord listener 注册与按需启动。"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

_COORD_LISTENER_SPECS: tuple[tuple[str, str, str | None], ...] = (
    (
        "pallas.core.platform.shard.coord.repeater_buffer",
        "start_repeater_buffer_redis_listener",
        "repeater",
    ),
    (
        "pallas.core.platform.shard.coord.repeater_reply_buffer",
        "start_repeater_reply_buffer_redis_listener",
        "repeater",
    ),
    ("pallas.core.platform.shard.coord.dream_drift", "start_dream_drift_redis_listener", "dream"),
    ("pallas.core.platform.shard.coord.duel_qte_redis", "start_duel_qte_redis_listeners", "duel"),
    ("pallas.core.platform.shard.coord.bot_action", "start_bot_action_redis_listener", None),
)


def coord_listener_plugin_name(plugin_hint: str | None) -> str | None:
    return (plugin_hint or "").strip() or None


def coord_listener_should_start(plugin_hint: str | None) -> bool:
    plugin_name = coord_listener_plugin_name(plugin_hint)
    if plugin_name is None:
        return True
    try:
        from packages.help.global_disable import resolve_global_disabled_plugin_names

        if plugin_name in resolve_global_disabled_plugin_names():
            return False
    except Exception:
        pass
    try:
        import nonebot

        return nonebot.get_plugin(plugin_name) is not None
    except Exception:
        return True


def coord_listener_starters() -> tuple[Callable[[], None], ...]:
    starters: list[Callable[[], None]] = []
    for module_path, attr, plugin_hint in _COORD_LISTENER_SPECS:
        if not coord_listener_should_start(plugin_hint):
            continue
        mod = importlib.import_module(module_path)
        starters.append(getattr(mod, attr))
    return tuple(starters)
