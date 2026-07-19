from nonebot import get_bots, logger
from nonebot.adapters.onebot.v11 import Bot
from nonebot_plugin_apscheduler import scheduler

from .runtime import (
    cached_doubt_friend,
    fetch_doubt_friends,
    get_nickname,
    load_doubt_poll_state,
    notify_admins,
    pending_friend,
    plugin_config,
    request_handler_plugin_disabled,
    save_doubt_poll_state,
    set_last_notified,
)
from .texts import REQUEST_HANDLER_HELP_HINT


@scheduler.scheduled_job(
    "interval",
    hours=4,
    id="request_handler_poll_doubt_friends",
    coalesce=True,
    max_instances=1,
)
async def poll_doubt_friends_job() -> None:
    if not plugin_config().request_handler_poll_doubt_friends:
        return
    primed_bots, notified_map = load_doubt_poll_state()
    state_updated = False
    for bot in get_bots().values():
        if not isinstance(bot, Bot):
            continue
        bot_id = int(bot.self_id)
        bot_key = str(bot_id)
        if await request_handler_plugin_disabled(bot_id=bot_id):
            continue
        try:
            doubts = await fetch_doubt_friends(bot)
        except Exception as e:
            logger.debug(f"bot [{bot_key}] poll doubt friends failed: {e}")
            continue
        cached_doubt_friend[bot_key] = doubts
        current_uids = set(doubts.keys())
        pending_keys = pending_friend.get(bot_key, {})

        if bot_key not in primed_bots:
            notified_map[bot_key] = set(current_uids)
            primed_bots.add(bot_key)
            state_updated = True
            continue

        notified_set = notified_map.setdefault(bot_key, set())
        before_prune = frozenset(notified_set)
        notified_set &= current_uids
        if before_prune != frozenset(notified_set):
            state_updated = True

        for uid in sorted(current_uids):
            if uid in pending_keys:
                continue
            if uid in notified_set:
                continue
            nickname = await get_nickname(bot, int(uid))
            msg = f"[好友申请]\n申请人：{nickname}（{uid}）\n{REQUEST_HANDLER_HELP_HINT}"
            if await notify_admins(bot, msg, kind="friend", target_id=uid):
                set_last_notified(bot_key, "friend", uid)
                notified_set.add(uid)
                state_updated = True
            else:
                logger.warning(f"bot [{bot_key}] doubt friends notify_admins failed uid={uid}")

        notified_map[bot_key] = notified_set

    if state_updated:
        save_doubt_poll_state(primed_bots, notified_map)
