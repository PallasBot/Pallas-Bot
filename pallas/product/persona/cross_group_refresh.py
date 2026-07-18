from __future__ import annotations

import time

from nonebot import logger

from pallas.core.foundation.db import make_bot_config_repository, make_group_config_repository, make_message_repository
from pallas.product.persona.cross_group_profiler import build_bot_cross_group_persona
from pallas.product.persona.group_profiler import DEFAULT_WINDOW_HOURS
from pallas.product.persona.loader import invalidate_persona_cache

_dirty_bot_ids: set[int] = set()
_DEFAULT_BOT_BATCH_SIZE = 16
_MAX_GROUPS_PER_BOT = 128


def mark_bot_cross_group_dirty(bot_id: int) -> None:
    _dirty_bot_ids.add(int(bot_id))


def pop_dirty_bot_cross_group_batch(limit: int) -> list[int]:
    size = max(0, int(limit))
    if size <= 0 or not _dirty_bot_ids:
        return []
    batch = sorted(_dirty_bot_ids)[:size]
    _dirty_bot_ids.difference_update(batch)
    return batch


def clear_bot_cross_group_dirty_state() -> None:
    _dirty_bot_ids.clear()


async def mark_bots_cross_group_dirty_for_group(group_id: int, *, window_hours: int = DEFAULT_WINDOW_HOURS) -> None:
    message_repo = make_message_repository()
    now_ts = int(time.time())
    cutoff = now_ts - int(window_hours) * 3600
    list_bots = getattr(message_repo, "list_recent_bot_ids_for_group", None)
    if not callable(list_bots):
        return
    try:
        bot_ids = await list_bots(int(group_id), since_time=cutoff)
    except Exception as exc:
        logger.warning("cross_group_refresh list bots failed group={}: {}", group_id, exc)
        return
    for bot_id in bot_ids:
        mark_bot_cross_group_dirty(int(bot_id))


async def refresh_bot_cross_group_persona(
    bot_id: int,
    *,
    window_hours: int = DEFAULT_WINDOW_HOURS,
) -> bool:
    bid = int(bot_id)
    now_ts = int(time.time())
    cutoff = now_ts - int(window_hours) * 3600

    message_repo = make_message_repository()
    list_groups = getattr(message_repo, "list_recent_group_ids_for_bot", None)
    if not callable(list_groups):
        return False

    group_ids = await list_groups(bid, since_time=cutoff, limit=_MAX_GROUPS_PER_BOT)
    group_repo = make_group_config_repository()
    group_profiles: list[tuple[int, dict]] = []
    for gid in group_ids:
        group_config = await group_repo.get(int(gid))
        style_profile = getattr(group_config, "style_profile", None) if group_config is not None else None
        if isinstance(style_profile, dict):
            group_profiles.append((int(gid), style_profile))

    persona = build_bot_cross_group_persona(
        bot_id=bid,
        group_profiles=group_profiles,
        now_ts=now_ts,
        window_hours=window_hours,
    )
    bot_repo = make_bot_config_repository()
    existing = await bot_repo.get(bid)
    existing_persona = getattr(existing, "persona", None) if existing is not None else None
    merged = dict(persona)
    if isinstance(existing_persona, dict):
        for key in (
            "seed",
            "seed_override",
            "self_aliases",
            "alias_names",
            "knowledges",
            "relationships",
            "layers",
        ):
            if key in existing_persona and key not in merged:
                merged[key] = existing_persona[key]
    from pallas.product.persona.seed import ensure_persona_auto_seed

    merged = ensure_persona_auto_seed(merged, bid)
    await bot_repo.upsert_field(bid, "persona", merged)
    invalidate_persona_cache(bid)
    return True


async def refresh_dirty_bot_cross_group_batch(
    *,
    limit: int = _DEFAULT_BOT_BATCH_SIZE,
    window_hours: int = DEFAULT_WINDOW_HOURS,
) -> int:
    refreshed = 0
    for bot_id in pop_dirty_bot_cross_group_batch(limit):
        try:
            ok = await refresh_bot_cross_group_persona(bot_id, window_hours=window_hours)
        except Exception as exc:
            logger.warning("cross_group_refresh failed bot={}: {}", bot_id, exc)
            continue
        if ok:
            refreshed += 1
    return refreshed
