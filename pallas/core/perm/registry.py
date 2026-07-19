"""命令 ID与默认权限等级；可被 PALLAS_COMMAND_PERMISSION_OVERRIDES 覆盖。"""

from __future__ import annotations

from typing import Literal

PermissionLevel = Literal["superuser", "group_moderator", "bot_moderator", "staff", "everyone"]

VALID_LEVELS: frozenset[str] = frozenset({
    "superuser",
    "group_moderator",
    "bot_moderator",
    "staff",
    "everyone",
})

COMMAND_ID_ALIASES: dict[str, str] = {
    "ollama.chat": "llm_chat.chat",
    "ollama.clear": "llm_chat.clear",
}


def canonical_command_id(command_id: str) -> str:
    cid = (command_id or "").strip()
    return COMMAND_ID_ALIASES.get(cid, cid)


def command_override_keys(command_id: str) -> tuple[str, ...]:
    cid = (command_id or "").strip()
    canon = canonical_command_id(cid)
    keys: list[str] = []
    for key in (cid, canon):
        if key and key not in keys:
            keys.append(key)
    for legacy, current in COMMAND_ID_ALIASES.items():
        if current == canon and legacy not in keys:
            keys.append(legacy)
    return tuple(keys)


DEFAULT_COMMAND_PERMISSIONS: dict[str, PermissionLevel] = {
    "pb_core.status": "superuser",
    "pb_core.console": "superuser",
    "pb_core.plugins": "superuser",
    "pb_core.update_check": "superuser",
    "pb_core.restart": "superuser",
    "help.help": "everyone",
    "help.plugin_enable": "staff",
    "help.plugin_disable": "staff",
    "help.plugin_enable_all": "staff",
    "help.plugin_disable_all": "staff",
    "blacklist.add": "staff",
    "blacklist.remove": "staff",
    "blacklist.list": "staff",
    "bot_status.status": "bot_moderator",
    "bot_status.count": "everyone",
    "bot_status.test_mail": "superuser",
    "greeting.set_friend_welcome": "bot_moderator",
    "greeting.clear_friend_welcome": "bot_moderator",
    "greeting.set_group_welcome": "group_moderator",
    "greeting.clear_group_welcome": "group_moderator",
    "relogin.relogin": "bot_moderator",
    "relogin.create": "superuser",
    "request.list_friends": "bot_moderator",
    "request.approve_latest": "bot_moderator",
    "request.reject_latest": "bot_moderator",
    "request.approve_friend": "bot_moderator",
    "request.approve_all_friends": "bot_moderator",
    "request.reject_all_friends": "bot_moderator",
    "request.list_groups": "bot_moderator",
    "request.approve_group": "bot_moderator",
    "request.approve_all_groups": "bot_moderator",
    "request.reject_all_groups": "bot_moderator",
    "request.reject_friend": "bot_moderator",
    "request.reject_group": "bot_moderator",
    "request.auto_accept_status": "bot_moderator",
    "request.enable_auto_friend": "bot_moderator",
    "request.disable_auto_friend": "bot_moderator",
    "request.enable_auto_group": "bot_moderator",
    "request.disable_auto_group": "bot_moderator",
    "request.approval_reply": "bot_moderator",
    "sing.ncm_login": "superuser",
    "sing.ncm_logout": "superuser",
    "draw.draw": "everyone",
    "connectivity.probe": "everyone",
    "repeater.ban": "staff",
    "repeater.ban_latest": "staff",
    "dream.ban_cleanup": "staff",
    "roulette.mode_switch": "staff",
    "duel.duel": "everyone",
    "duel.cage": "everyone",
    "duel.reload_events": "group_moderator",
    "llm_chat.chat": "everyone",
    "llm_chat.clear": "everyone",
    "llm_chat.switch_model": "superuser",
    "llm_chat.unload_model": "superuser",
    "llm_chat.status": "superuser",
    "maa.bind": "everyone",
    "maa.switch_device": "everyone",
    "maa.device_alias": "everyone",
    "maa.control": "everyone",
    "maa.raw_task": "everyone",
    "maa.clear_queue": "everyone",
    "maa.status": "everyone",
}


def normalize_level(raw: str | None) -> PermissionLevel:
    s = (raw or "").strip().lower()
    if s in VALID_LEVELS:
        return s  # type: ignore[return-value]
    return "everyone"


def resolved_level(command_id: str, overrides: dict[str, str]) -> PermissionLevel:
    from .schema import default_level_for

    for key in command_override_keys(command_id):
        if key in overrides:
            raw_o = (overrides[key] or "").strip().lower()
            if raw_o not in VALID_LEVELS:
                return normalize_level(default_level_for(canonical_command_id(command_id)))
            return raw_o  # type: ignore[return-value]
    return normalize_level(default_level_for(canonical_command_id(command_id)))
