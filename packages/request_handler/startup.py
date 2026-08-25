from nonebot import get_bots, get_driver, logger
from nonebot.adapters.onebot.v11 import Bot
from nonebot_plugin_apscheduler import scheduler

from .runtime import (
    cached_doubt_friend,
    clear_joined_group_state,
    fetch_doubt_friends,
    get_nickname,
    joined_groups,
    load_doubt_poll_state,
    notify_admins,
    pending_friend,
    pending_group,
    plugin_config,
    request_handler_plugin_disabled,
    save_doubt_poll_state,
    set_last_notified,
)
from .texts import REQUEST_HANDLER_HELP_HINT


@get_driver().on_bot_connect
async def on_bot_connect(bot: Bot) -> None:
    if bot.type != "OneBot V11" or not bot.self_id.isnumeric():
        return
    bot_key = str(bot.self_id)
    try:
        result = await bot.get_group_list()
    except Exception as e:
        logger.debug(f"bot [{bot_key}] get_group_list on connect failed: {e}")
        return
    group_ids = {str(group.get("group_id")) for group in result if isinstance(group, dict) and group.get("group_id")}
    if not group_ids:
        return
    joined_groups[bot_key] = group_ids
    for group_key in list(pending_group.get(bot_key, {})):
        if group_key in group_ids:
            clear_joined_group_state(bot_key, group_key)


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
                logger.warning(
                    f"Bot [{bot_key}] failed to notify admins about doubtful friend request from user [{uid}]"
                )

        notified_map[bot_key] = notified_set

    if state_updated:
        save_doubt_poll_state(primed_bots, notified_map)
