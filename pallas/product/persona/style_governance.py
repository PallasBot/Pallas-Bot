"""群风格治理：按群采集、按 Bot+群注入的独立开关，以及清空群风格画像的原子操作。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from nonebot import logger

from pallas.core.foundation.db import make_group_config_repository
from pallas.core.foundation.fs_lock import atomic_write_text, interprocess_file_lock
from pallas.core.foundation.paths import plugin_data_dir
from pallas.product.persona.loader import invalidate_persona_cache

if TYPE_CHECKING:
    from pathlib import Path


def group_style_governance_path() -> Path:
    return plugin_data_dir("pb_webui") / "group_style_governance.json"


def group_style_governance_lock_path() -> Path:
    return group_style_governance_path().with_suffix(".lock")


def _load_state() -> dict[str, dict]:
    try:
        raw = json.loads(group_style_governance_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return {"groups": {}, "bots": {}}
    if not isinstance(raw, dict):
        return {"groups": {}, "bots": {}}
    return {
        "groups": raw.get("groups") if isinstance(raw.get("groups"), dict) else {},
        "bots": raw.get("bots") if isinstance(raw.get("bots"), dict) else {},
    }


def _save_state(state: dict[str, dict]) -> None:
    atomic_write_text(
        group_style_governance_path(),
        json.dumps(state, ensure_ascii=False, separators=(",", ":")),
    )


def _group_entry(state: dict[str, dict], group_id: int) -> dict:
    entry = state["groups"].get(str(group_id))
    return entry if isinstance(entry, dict) else {}


def _group_flag(state: dict[str, dict], group_id: int, key: str, default: bool) -> bool:
    value = _group_entry(state, group_id).get(key)
    return default if not isinstance(value, bool) else value


def _group_collection_enabled(state: dict[str, dict], group_id: int) -> bool:
    return _group_flag(state, group_id, "collection_enabled", True)


def _group_injection_default(state: dict[str, dict], group_id: int) -> bool:
    return _group_flag(state, group_id, "injection_enabled", True)


def _bot_injection_enabled(state: dict[str, dict], bot_id: int, group_id: int) -> bool:
    bot_entry = state["bots"].get(str(bot_id))
    if not isinstance(bot_entry, dict):
        return _group_injection_default(state, group_id)
    group_entry = bot_entry.get(str(group_id))
    if not isinstance(group_entry, dict):
        return _group_injection_default(state, group_id)
    value = group_entry.get("injection_enabled")
    return _group_injection_default(state, group_id) if not isinstance(value, bool) else value


def group_style_status(*, bot_id: int, group_id: int) -> dict[str, bool]:
    """返回该 Bot+群当前的采集与注入生效状态（缺失时默认启用）。"""
    state = _load_state()
    return {
        "collection_enabled": _group_collection_enabled(state, group_id),
        "injection_enabled": _bot_injection_enabled(state, bot_id, group_id),
    }


def group_style_collection_enabled(*, group_id: int) -> bool:
    """该群当前是否允许采集群风格（缺失时默认启用）。"""
    return _group_collection_enabled(_load_state(), group_id)


def group_style_injection_enabled(*, bot_id: int, group_id: int) -> bool:
    """该 Bot+群当前是否注入群风格画像（缺失时默认启用）。"""
    return _bot_injection_enabled(_load_state(), bot_id, group_id)


async def set_group_style_collection(*, group_id: int, enabled: bool) -> dict[str, bool]:
    """按群开关采集；返回中的 injection_enabled 为群级回退值，非逐 Bot 生效值。"""
    enabled = bool(enabled)
    with interprocess_file_lock(group_style_governance_lock_path()):
        state = _load_state()
        entry = _group_entry(state, group_id)
        entry["collection_enabled"] = enabled
        state["groups"][str(group_id)] = entry
        _save_state(state)
    logger.info("Group style collection for group [{}] set to [{}]", group_id, enabled)
    return {"collection_enabled": enabled, "injection_enabled": _group_injection_default(state, group_id)}


async def set_group_style_injection(*, bot_id: int, group_id: int, enabled: bool) -> dict[str, bool]:
    """按 Bot+群开关注入，其余 Bot/群不受影响。"""
    enabled = bool(enabled)
    with interprocess_file_lock(group_style_governance_lock_path()):
        state = _load_state()
        bots = state["bots"].get(str(bot_id))
        if not isinstance(bots, dict):
            bots = {}
            state["bots"][str(bot_id)] = bots
        bots[str(group_id)] = {"injection_enabled": enabled}
        _save_state(state)
    logger.info("Group style injection for bot [{}] in group [{}] set to [{}]", bot_id, group_id, enabled)
    invalidate_persona_cache(bot_id=bot_id)
    return {
        "collection_enabled": _group_collection_enabled(state, group_id),
        "injection_enabled": enabled,
    }


async def clear_group_style(*, group_id: int, continue_learning: bool) -> dict[str, bool]:
    """删除该群 style_profile 并按 continue_learning 写群级治理状态。

    返回中的 injection_enabled 为群级回退值，非逐 Bot 生效值。
    """
    continue_learning = bool(continue_learning)
    with interprocess_file_lock(group_style_governance_lock_path()):
        state = _load_state()
        entry = _group_entry(state, group_id)
        entry["collection_enabled"] = continue_learning
        if not continue_learning:
            entry["injection_enabled"] = False
            for _bot_id, bot_entry in list(state["bots"].items()):
                if isinstance(bot_entry, dict):
                    bot_entry.pop(str(group_id), None)
            logger.info("Group style cleared and fully paused for group [{}]", group_id)
        else:
            logger.info("Group style cleared but learning resumed for group [{}]", group_id)
        state["groups"][str(group_id)] = entry
        _save_state(state)
    repo = make_group_config_repository()
    await repo.upsert_field(group_id, "style_profile", None)
    invalidate_persona_cache()
    return {
        "collection_enabled": continue_learning,
        "injection_enabled": _group_injection_default(state, group_id),
    }
