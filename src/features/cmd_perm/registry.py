"""命令 ID（插件前缀.动作）与默认权限等级；可被 PALLAS_COMMAND_PERMISSION_OVERRIDES 覆盖。"""

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

DEFAULT_COMMAND_PERMISSIONS: dict[str, PermissionLevel] = {
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
    "draw.gateway": "everyone",
    "connectivity.probe": "everyone",
    "repeater.ban": "staff",
    "repeater.ban_latest": "staff",
    "dream.ban_cleanup": "staff",
    "roulette.mode_switch": "staff",
    "duel.duel": "everyone",
    "duel.cage": "everyone",
    "duel.reload_events": "group_moderator",
    "ollama.chat": "everyone",
    "ollama.clear": "everyone",
    "ollama.unload": "staff",
    "ollama.set_model": "superuser",
    "maa.bind": "everyone",
    "maa.control": "everyone",
    "maa.status": "everyone",
}


def normalize_level(raw: str | None) -> PermissionLevel:
    s = (raw or "").strip().lower()
    if s in VALID_LEVELS:
        return s  # type: ignore[return-value]
    return "everyone"


def resolved_level(command_id: str, overrides: dict[str, str]) -> PermissionLevel:
    from .schema import default_level_for

    cid = (command_id or "").strip()
    if cid in overrides:
        raw_o = (overrides[cid] or "").strip().lower()
        if raw_o not in VALID_LEVELS:
            return normalize_level(default_level_for(cid))
        return raw_o  # type: ignore[return-value]
    return normalize_level(default_level_for(cid))
