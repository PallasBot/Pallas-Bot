"""同群独占 + 主持牛 ingress 门控：从 PluginMetadata.extra 读取，勿 import 插件包。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from nonebot import get_loaded_plugins

from pallas.core.foundation.command_prefix import matches_command_prefix
from pallas.core.platform.ingress.plugin_command_plaintext import extract_command_prefixes_from_menu_data
from pallas.core.platform.multi_bot.dedup import needs_group_host_bot_gate
from pallas.core.platform.shard.coord.group_gate import is_owned_gate_holder_sync
from pallas.core.platform.shard.coord.hosted_activity_coord import coord_session_active, hosted_activity_live

_SPECS_CACHE: tuple[HostedActivityIngressSpec, ...] | None = None


@dataclass(frozen=True, slots=True)
class HostedActivityIngressSpec:
    plugin_key: str
    activity_namespace: str
    command_prefixes: tuple[str, ...]
    always_pass_prefixes: tuple[str, ...]
    session_flag: str = "session_active"
    speak_at_fleet_bot_only: bool = True


def _matches_prefix(text: str, prefixes: tuple[str, ...]) -> bool:
    if not text:
        return False
    return any(matches_command_prefix(text, prefix) for prefix in prefixes)


def _parse_spec(raw: dict[str, Any], *, menu_data: list[dict[str, Any]] | None) -> HostedActivityIngressSpec | None:
    plugin_key = str(raw.get("plugin_key") or "").strip()
    activity_namespace = str(raw.get("activity_namespace") or "").strip()
    if not plugin_key or not activity_namespace:
        return None

    explicit = raw.get("command_prefixes")
    if isinstance(explicit, (list, tuple)) and explicit:
        command_prefixes = tuple(str(p).strip() for p in explicit if str(p).strip())
    else:
        command_prefixes = extract_command_prefixes_from_menu_data(menu_data)

    always_raw = raw.get("always_pass_prefixes")
    if isinstance(always_raw, (list, tuple)):
        always_pass_prefixes = tuple(str(p).strip() for p in always_raw if str(p).strip())
    else:
        always_pass_prefixes = ()

    session_flag = str(raw.get("session_flag") or "session_active").strip() or "session_active"
    speak_at_fleet_bot_only = raw.get("speak_at_fleet_bot_only", True)
    if not isinstance(speak_at_fleet_bot_only, bool):
        speak_at_fleet_bot_only = True

    if not command_prefixes and not speak_at_fleet_bot_only:
        return None

    return HostedActivityIngressSpec(
        plugin_key=plugin_key,
        activity_namespace=activity_namespace,
        command_prefixes=command_prefixes,
        always_pass_prefixes=always_pass_prefixes,
        session_flag=session_flag,
        speak_at_fleet_bot_only=speak_at_fleet_bot_only,
    )


def loaded_hosted_activity_specs() -> tuple[HostedActivityIngressSpec, ...]:
    global _SPECS_CACHE
    if _SPECS_CACHE is not None:
        return _SPECS_CACHE

    specs: list[HostedActivityIngressSpec] = []
    for plugin in get_loaded_plugins():
        meta = getattr(plugin, "metadata", None)
        extra = getattr(meta, "extra", None) if meta is not None else None
        if not isinstance(extra, dict):
            continue
        raw = extra.get("hosted_activity_ingress")
        if not isinstance(raw, dict):
            continue
        menu_data = extra.get("menu_data")
        spec = _parse_spec(raw, menu_data=menu_data if isinstance(menu_data, list) else None)
        if spec is not None:
            specs.append(spec)
    _SPECS_CACHE = tuple(specs)
    return _SPECS_CACHE


def clear_hosted_activity_ingress_cache() -> None:
    global _SPECS_CACHE
    _SPECS_CACHE = None


def spec_matches_in_room_command(spec: HostedActivityIngressSpec, plain: str) -> bool:
    text = (plain or "").strip()
    if not _matches_prefix(text, spec.command_prefixes):
        return False
    return not _matches_prefix(text, spec.always_pass_prefixes)


def spec_matches_speak_traffic(
    spec: HostedActivityIngressSpec,
    group_id: int,
    plain: str,
    *,
    at_fleet_bot: bool,
) -> bool:
    text = (plain or "").strip()
    if _matches_prefix(text, spec.command_prefixes):
        return False
    if not coord_session_active(spec.activity_namespace, group_id, session_flag=spec.session_flag):
        return False
    if spec.speak_at_fleet_bot_only:
        return at_fleet_bot
    return bool(text)


def spec_host_gate_passes(
    spec: HostedActivityIngressSpec,
    bot_id: int,
    group_id: int,
    plain: str,
    *,
    at_fleet_bot: bool,
) -> bool:
    in_room = spec_matches_in_room_command(spec, plain)
    speak = spec_matches_speak_traffic(spec, group_id, plain, at_fleet_bot=at_fleet_bot)
    text = (plain or "").strip()
    open_or_end = _matches_prefix(text, spec.always_pass_prefixes)

    if not in_room and not speak and not open_or_end:
        return True

    if not needs_group_host_bot_gate():
        return True

    if not hosted_activity_live(
        activity_namespace=spec.activity_namespace,
        plugin_key=spec.plugin_key,
        group_id=group_id,
    ):
        return True

    return is_owned_gate_holder_sync(spec.plugin_key, int(group_id), int(bot_id))


def hosted_activity_ingress_passes(
    bot_id: int,
    group_id: int,
    plain: str,
    *,
    at_fleet_bot: bool = False,
) -> bool:
    """False → ingress 丢弃。"""
    for spec in loaded_hosted_activity_specs():
        if not spec_host_gate_passes(spec, bot_id, group_id, plain, at_fleet_bot=at_fleet_bot):
            return False
    return True
