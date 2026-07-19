from nonebot import on_command, on_message, on_request
from nonebot.adapters import Event
from nonebot.adapters.onebot.v11 import (
    Bot,
    FriendRequestEvent,
    GroupRequestEvent,
    Message,
    MessageEvent,
    PrivateMessageEvent,
)
from nonebot.exception import ActionFailed
from nonebot.params import CommandArg
from nonebot.rule import Rule

from packages.request_handler.approval_notice_text import parse_approval_notice_meta
from packages.request_handler.approval_reply_text import (
    classify_approval_reply_text,
    extract_approval_reply_text_from_body,
)
from packages.request_handler.runtime import (
    approval_notice_map,
    approve_friend_by_uid,
    approve_group_invite_by_gid,
    cached_doubt_friend,
    clear_quick_approve_state,
    failure_cleanup_friend,
    failure_cleanup_group,
    fetch_doubt_friends,
    get_group_name,
    get_last_notified,
    get_nickname,
    notify_admins,
    notify_ts_expired,
    pending_friend,
    pending_group,
    persist_approval_notice_map,
    persist_pending_friend,
    persist_pending_group,
    reject_friend_by_uid,
    reject_group_invite_by_gid,
    request_handler_plugin_disabled,
    set_last_notified,
)
from packages.request_handler.texts import (
    APPROVE_ALL_FRIENDS_COMMAND,
    APPROVE_ALL_GROUPS_ALIASES,
    APPROVE_ALL_GROUPS_COMMAND,
    APPROVE_FRIEND_COMMAND,
    APPROVE_GROUP_COMMAND,
    APPROVE_LATEST_COMMAND,
    AUTO_ACCEPT_STATUS_ALIASES,
    AUTO_ACCEPT_STATUS_COMMAND,
    DISABLE_AUTO_FRIEND_COMMAND,
    DISABLE_AUTO_GROUP_COMMAND,
    ENABLE_AUTO_FRIEND_COMMAND,
    ENABLE_AUTO_GROUP_COMMAND,
    LIST_FRIEND_ALIASES,
    LIST_FRIEND_COMMAND,
    LIST_GROUP_ALIASES,
    LIST_GROUP_COMMAND,
    REJECT_ALL_FRIENDS_COMMAND,
    REJECT_ALL_GROUPS_ALIASES,
    REJECT_ALL_GROUPS_COMMAND,
    REJECT_FRIEND_COMMAND,
    REJECT_GROUP_COMMAND,
    REJECT_LATEST_COMMAND,
    REQUEST_HANDLER_HELP_HINT,
    build_list_tail,
    build_quick_action_arg_hint,
    build_quick_action_missing_hint,
)
from pallas.core.foundation.config import BotConfig, GroupConfig, UserConfig, user_is_bot_admin
from pallas.core.perm import private_message_permission_for_command, satisfies_command_permission

request_cmd = on_request(priority=14, block=False)

list_friends_cmd = on_command(
    LIST_FRIEND_COMMAND,
    aliases=set(LIST_FRIEND_ALIASES),
    priority=5,
    block=True,
    permission=private_message_permission_for_command("request.list_friends"),
)
approve_latest_cmd = on_command(
    APPROVE_LATEST_COMMAND,
    priority=5,
    block=True,
    permission=private_message_permission_for_command("request.approve_latest"),
)
reject_latest_cmd = on_command(
    REJECT_LATEST_COMMAND,
    priority=5,
    block=True,
    permission=private_message_permission_for_command("request.reject_latest"),
)
approve_friend_cmd = on_command(
    APPROVE_FRIEND_COMMAND,
    priority=5,
    block=True,
    permission=private_message_permission_for_command("request.approve_friend"),
)
approve_all_friends_cmd = on_command(
    APPROVE_ALL_FRIENDS_COMMAND,
    priority=5,
    block=True,
    permission=private_message_permission_for_command("request.approve_all_friends"),
)
reject_all_friends_cmd = on_command(
    REJECT_ALL_FRIENDS_COMMAND,
    priority=5,
    block=True,
    permission=private_message_permission_for_command("request.reject_all_friends"),
)
list_groups_cmd = on_command(
    LIST_GROUP_COMMAND,
    aliases=set(LIST_GROUP_ALIASES),
    priority=5,
    block=True,
    permission=private_message_permission_for_command("request.list_groups"),
)
approve_group_cmd = on_command(
    APPROVE_GROUP_COMMAND,
    priority=5,
    block=True,
    permission=private_message_permission_for_command("request.approve_group"),
)
approve_all_groups_cmd = on_command(
    APPROVE_ALL_GROUPS_COMMAND,
    aliases=set(APPROVE_ALL_GROUPS_ALIASES),
    priority=5,
    block=True,
    permission=private_message_permission_for_command("request.approve_all_groups"),
)
reject_all_groups_cmd = on_command(
    REJECT_ALL_GROUPS_COMMAND,
    aliases=set(REJECT_ALL_GROUPS_ALIASES),
    priority=5,
    block=True,
    permission=private_message_permission_for_command("request.reject_all_groups"),
)
reject_friend_cmd = on_command(
    REJECT_FRIEND_COMMAND,
    priority=5,
    block=True,
    permission=private_message_permission_for_command("request.reject_friend"),
)
reject_group_cmd = on_command(
    REJECT_GROUP_COMMAND,
    priority=5,
    block=True,
    permission=private_message_permission_for_command("request.reject_group"),
)
auto_accept_status_cmd = on_command(
    AUTO_ACCEPT_STATUS_COMMAND,
    aliases=set(AUTO_ACCEPT_STATUS_ALIASES),
    priority=5,
    block=True,
    permission=private_message_permission_for_command("request.auto_accept_status"),
)
enable_auto_friend_cmd = on_command(
    ENABLE_AUTO_FRIEND_COMMAND,
    priority=5,
    block=True,
    permission=private_message_permission_for_command("request.enable_auto_friend"),
)
disable_auto_friend_cmd = on_command(
    DISABLE_AUTO_FRIEND_COMMAND,
    priority=5,
    block=True,
    permission=private_message_permission_for_command("request.disable_auto_friend"),
)
enable_auto_group_cmd = on_command(
    ENABLE_AUTO_GROUP_COMMAND,
    priority=5,
    block=True,
    permission=private_message_permission_for_command("request.enable_auto_group"),
)
disable_auto_group_cmd = on_command(
    DISABLE_AUTO_GROUP_COMMAND,
    priority=5,
    block=True,
    permission=private_message_permission_for_command("request.disable_auto_group"),
)


async def approval_reply_rule(bot: Bot, event: Event) -> bool:
    if not isinstance(event, PrivateMessageEvent):
        return False
    has_perm = False
    for perm_id in ("request.approval_reply", "request.reject_friend", "request.reject_group"):
        if await satisfies_command_permission(bot, event, perm_id):
            has_perm = True
            break
    if not has_perm:
        return False
    if not event.reply:
        return False
    quoted_body = None
    if event.reply.message is not None:
        quoted_body = event.reply.message.extract_plain_text()
    bot_key = str(bot.self_id)
    mid = str(event.reply.message_id)
    bot_msgs = approval_notice_map.get(bot_key)
    if bot_msgs and mid in bot_msgs:
        meta = bot_msgs[mid]
        ts = float(meta.get("ts") or 0)
        if ts and notify_ts_expired(ts):
            bot_msgs.pop(mid, None)
            if not bot_msgs:
                approval_notice_map.pop(bot_key, None)
            persist_approval_notice_map(bot_key)
            return False
        return True
    return parse_approval_notice_meta(quoted_body) is not None


approval_reply_cmd = on_message(rule=Rule(approval_reply_rule), priority=4, block=True)


@approval_reply_cmd.handle()
async def handle_approval_reply(bot: Bot, event: PrivateMessageEvent):
    bot_key = str(bot.self_id)
    mid = str(event.reply.message_id)
    quoted_body = None
    if event.reply and event.reply.message is not None:
        quoted_body = event.reply.message.extract_plain_text()
    meta = approval_notice_map.get(bot_key, {}).get(mid)
    if not meta:
        meta = parse_approval_notice_meta(quoted_body)
    if not meta:
        return
    text = extract_approval_reply_text_from_body(event.get_plaintext() or "", quoted_body)
    action = classify_approval_reply_text(text)
    if action is None:
        await approval_reply_cmd.finish("引用审批消息后，正文须为：同意 / 好 / 留空，或 拒绝 / 不要 / 否。")
    kind = str(meta["kind"])
    target_id = str(meta["target_id"])
    if action == "approve":
        if not await satisfies_command_permission(bot, event, "request.approval_reply"):
            await approval_reply_cmd.finish("你没有引用同意的权限。")
        if kind == "friend":
            ok, msg = await approve_friend_by_uid(bot, bot_key, target_id)
        else:
            ok, msg = await approve_group_invite_by_gid(bot, bot_key, target_id)
    else:
        reject_perm = "request.reject_friend" if kind == "friend" else "request.reject_group"
        if not await satisfies_command_permission(bot, event, reject_perm):
            await approval_reply_cmd.finish("你没有引用拒绝的权限。")
        if kind == "friend":
            ok, msg = await reject_friend_by_uid(bot, bot_key, target_id)
        else:
            ok, msg = await reject_group_invite_by_gid(bot, bot_key, target_id)
    if ok:
        clear_quick_approve_state(bot_key, kind, target_id)
    await approval_reply_cmd.finish(msg)


@request_cmd.handle()
async def handle_friend_request(bot: Bot, event: FriendRequestEvent):
    bot_id = int(bot.self_id)
    bot_key = str(bot_id)
    pending_friend.setdefault(bot_key, {})[str(event.user_id)] = event.flag
    persist_pending_friend(bot_key)

    bot_config = BotConfig(bot_id)
    if await bot_config.auto_accept_friend():
        await event.approve(bot)
        pending_friend.get(bot_key, {}).pop(str(event.user_id), None)
        persist_pending_friend(bot_key)
        return

    if not await request_handler_plugin_disabled(bot_id=bot_id):
        nickname = await get_nickname(bot, event.user_id)
        msg = (
            f"[好友申请]\n申请人：{nickname}（{event.user_id}）\n"
            f"验证：{event.comment or '-'}\n{REQUEST_HANDLER_HELP_HINT}"
        )
        if await notify_admins(bot, msg, kind="friend", target_id=str(event.user_id)):
            set_last_notified(bot_key, "friend", str(event.user_id))


@list_friends_cmd.handle()
async def handle_list_friends(bot: Bot, event: MessageEvent):
    if not await satisfies_command_permission(bot, event, "request.list_friends"):
        return
    bot_key = str(bot.self_id)
    bot_pending = pending_friend.get(bot_key, {})

    # 获取被过滤的好友申请并缓存
    doubt_requests = await fetch_doubt_friends(bot)
    cached_doubt_friend[bot_key] = doubt_requests

    # 去重：被过滤列表中已在普通列表的不重复计数
    doubt_only = {uid: flag for uid, flag in doubt_requests.items() if uid not in bot_pending}
    total = len(bot_pending) + len(doubt_only)
    if total == 0:
        await list_friends_cmd.finish("暂无待处理好友申请")

    lines = [f"待处理好友申请（共 {total} 条）："]
    for uid in bot_pending.keys():
        nickname = await get_nickname(bot, int(uid))
        lines.append(f"  {nickname}（{uid}）")
    for uid in doubt_only.keys():
        nickname = await get_nickname(bot, int(uid))
        lines.append(f"  {nickname}（{uid}）")
    lines.append(build_list_tail("friend"))
    await list_friends_cmd.finish("\n".join(lines))


@approve_latest_cmd.handle()
async def handle_approve_latest(bot: Bot, event: MessageEvent, args: Message = CommandArg()):  # noqa: B008
    if not await satisfies_command_permission(bot, event, "request.approve_latest"):
        return
    arg = args.extract_plain_text().strip()
    if arg:
        await approve_latest_cmd.finish(build_quick_action_arg_hint(APPROVE_LATEST_COMMAND))
    bot_key = str(bot.self_id)
    entry = get_last_notified(bot_key)
    if not entry:
        await approve_latest_cmd.finish(build_quick_action_missing_hint(APPROVE_LATEST_COMMAND))
    kind, target_id, _ts = entry
    if kind == "friend":
        ok, msg = await approve_friend_by_uid(bot, bot_key, target_id)
    else:
        ok, msg = await approve_group_invite_by_gid(bot, bot_key, target_id)
    if ok:
        clear_quick_approve_state(bot_key, kind, target_id)
    await approve_latest_cmd.finish(msg)


@reject_latest_cmd.handle()
async def handle_reject_latest(bot: Bot, event: MessageEvent, args: Message = CommandArg()):  # noqa: B008
    if not await satisfies_command_permission(bot, event, "request.reject_latest"):
        return
    arg = args.extract_plain_text().strip()
    if arg:
        await reject_latest_cmd.finish(build_quick_action_arg_hint(REJECT_LATEST_COMMAND))
    bot_key = str(bot.self_id)
    entry = get_last_notified(bot_key)
    if not entry:
        await reject_latest_cmd.finish(build_quick_action_missing_hint(REJECT_LATEST_COMMAND))
    kind, target_id, _ts = entry
    if kind == "friend":
        ok, msg = await reject_friend_by_uid(bot, bot_key, target_id)
    else:
        ok, msg = await reject_group_invite_by_gid(bot, bot_key, target_id)
    if ok:
        clear_quick_approve_state(bot_key, kind, target_id)
    await reject_latest_cmd.finish(msg)


@approve_friend_cmd.handle()
async def handle_approve_friend(bot: Bot, event: MessageEvent, args: Message = CommandArg()):  # noqa: B008
    if not await satisfies_command_permission(bot, event, "request.approve_friend"):
        return
    arg = args.extract_plain_text().strip()
    if not arg.isdigit():
        await approve_friend_cmd.finish(f"格式：{APPROVE_FRIEND_COMMAND} <QQ号>")

    bot_key = str(bot.self_id)
    ok, msg = await approve_friend_by_uid(bot, bot_key, arg)
    if ok:
        clear_quick_approve_state(bot_key, "friend", arg)
    await approve_friend_cmd.finish(msg)


@reject_friend_cmd.handle()
async def handle_reject_friend(bot: Bot, event: MessageEvent, args: Message = CommandArg()):  # noqa: B008
    if not await satisfies_command_permission(bot, event, "request.reject_friend"):
        return
    arg = args.extract_plain_text().strip()
    if not arg.isdigit():
        await reject_friend_cmd.finish(f"格式：{REJECT_FRIEND_COMMAND} <QQ号>")

    bot_key = str(bot.self_id)
    ok, msg = await reject_friend_by_uid(bot, bot_key, arg)
    if ok:
        clear_quick_approve_state(bot_key, "friend", arg)
    await reject_friend_cmd.finish(msg)


@list_groups_cmd.handle()
async def handle_list_groups(bot: Bot, event: MessageEvent):
    if not await satisfies_command_permission(bot, event, "request.list_groups"):
        return
    bot_key = str(bot.self_id)
    bot_pending = pending_group.get(bot_key, {})
    if not bot_pending:
        await list_groups_cmd.finish("暂无待处理入群申请")
    lines = [f"待处理入群申请（共 {len(bot_pending)} 条）："]
    for group_key, req in bot_pending.items():
        nickname = await get_nickname(bot, req["user_id"])
        group_name = await get_group_name(bot, int(group_key))
        lines.append(f"  {group_name}（{group_key}）← {nickname}（{req['user_id']}）邀请")
    lines.append(build_list_tail("group"))
    await list_groups_cmd.finish("\n".join(lines))


@request_cmd.handle()
async def handle_group_request(bot: Bot, event: GroupRequestEvent):
    if event.sub_type == "invite":
        if await GroupConfig(event.group_id).is_banned() or await UserConfig(event.user_id).is_banned():
            await event.reject(bot)
            return

        bot_id = int(bot.self_id)
        bot_key = str(bot_id)
        group_key = str(event.group_id)
        pending_group.setdefault(bot_key, {})[group_key] = {
            "flag": event.flag,
            "sub_type": "invite",
            "user_id": event.user_id,
            "group_id": event.group_id,
            "comment": event.comment or "",
        }
        persist_pending_group(bot_key)

        bot_config = BotConfig(bot_id)
        if await bot_config.auto_accept_group() or await user_is_bot_admin(bot_id, event.user_id):
            await event.approve(bot)
            pending_group.get(bot_key, {}).pop(group_key, None)
            persist_pending_group(bot_key)
            return

        if not await request_handler_plugin_disabled(bot_id=bot_id):
            nickname = await get_nickname(bot, event.user_id)
            group_name = await get_group_name(bot, event.group_id)
            msg = (
                f"[入群邀请]\n"
                f"邀请人：{nickname}（{event.user_id}）\n"
                f"群：{group_name}（{event.group_id}）\n"
                f"{REQUEST_HANDLER_HELP_HINT}"
            )
            if await notify_admins(bot, msg, kind="group", target_id=group_key):
                set_last_notified(bot_key, "group", group_key)


@approve_all_friends_cmd.handle()
async def handle_approve_all_friends(bot: Bot, event: MessageEvent):
    if not await satisfies_command_permission(bot, event, "request.approve_all_friends"):
        return
    bot_key = str(bot.self_id)
    bot_pending = pending_friend.get(bot_key, {})
    doubt_requests = await fetch_doubt_friends(bot)
    cached_doubt_friend[bot_key] = doubt_requests

    if not bot_pending and not doubt_requests:
        await approve_all_friends_cmd.finish("暂无待处理好友申请")

    ok, fail = 0, 0
    cleared_friend_ids: set[str] = set()
    for uid, flag in list(bot_pending.items()):
        try:
            await bot.set_friend_add_request(flag=flag, approve=True)
            bot_pending.pop(uid, None)
            ok += 1
            cleared_friend_ids.add(uid)
        except ActionFailed:
            fail += 1
            failure_cleanup_friend(bot_key, uid)
            cleared_friend_ids.add(uid)
        except Exception:
            fail += 1
    persist_pending_friend(bot_key)

    for uid, flag in list(doubt_requests.items()):
        try:
            await bot.call_api("set_doubt_friends_add_request", flag=flag, approve=True)
            cached_doubt_friend[bot_key].pop(uid, None)
            ok += 1
            cleared_friend_ids.add(uid)
        except ActionFailed:
            fail += 1
            failure_cleanup_friend(bot_key, uid)
            cleared_friend_ids.add(uid)
        except Exception:
            fail += 1

    for uid in cleared_friend_ids:
        clear_quick_approve_state(bot_key, "friend", uid)

    await approve_all_friends_cmd.finish(f"已同意 {ok} 条好友申请" + (f"，{fail} 条失败" if fail else ""))


@reject_all_friends_cmd.handle()
async def handle_reject_all_friends(bot: Bot, event: MessageEvent):
    if not await satisfies_command_permission(bot, event, "request.reject_all_friends"):
        return
    bot_key = str(bot.self_id)
    bot_pending = pending_friend.get(bot_key, {})
    doubt_requests = await fetch_doubt_friends(bot)
    cached_doubt_friend[bot_key] = doubt_requests

    if not bot_pending and not doubt_requests:
        await reject_all_friends_cmd.finish("暂无待处理好友申请")

    ok, fail = 0, 0
    cleared_friend_ids: set[str] = set()
    for uid, flag in list(bot_pending.items()):
        try:
            await bot.set_friend_add_request(flag=flag, approve=False)
            bot_pending.pop(uid, None)
            ok += 1
            cleared_friend_ids.add(uid)
        except ActionFailed:
            fail += 1
            failure_cleanup_friend(bot_key, uid)
            cleared_friend_ids.add(uid)
        except Exception:
            fail += 1
    persist_pending_friend(bot_key)

    for uid, flag in list(doubt_requests.items()):
        try:
            await bot.call_api("set_doubt_friends_add_request", flag=flag, approve=False)
            cached_doubt_friend[bot_key].pop(uid, None)
            ok += 1
            cleared_friend_ids.add(uid)
        except ActionFailed:
            fail += 1
            failure_cleanup_friend(bot_key, uid)
            cleared_friend_ids.add(uid)
        except Exception:
            fail += 1

    for uid in cleared_friend_ids:
        clear_quick_approve_state(bot_key, "friend", uid)

    await reject_all_friends_cmd.finish(f"已拒绝 {ok} 条好友申请" + (f"，{fail} 条失败" if fail else ""))


@approve_all_groups_cmd.handle()
async def handle_approve_all_groups(bot: Bot, event: MessageEvent):
    if not await satisfies_command_permission(bot, event, "request.approve_all_groups"):
        return
    bot_key = str(bot.self_id)
    bot_pending = pending_group.get(bot_key, {})
    if not bot_pending:
        await approve_all_groups_cmd.finish("暂无待处理入群申请")
    ok, fail = 0, 0
    cleared_group_keys: set[str] = set()
    for key, req in list(bot_pending.items()):
        try:
            await bot.set_group_add_request(flag=req["flag"], sub_type="invite", approve=True)
            bot_pending.pop(key, None)
            ok += 1
            cleared_group_keys.add(key)
        except ActionFailed:
            fail += 1
            failure_cleanup_group(bot_key, key)
            cleared_group_keys.add(key)
        except Exception:
            fail += 1
    persist_pending_group(bot_key)
    for gkey in cleared_group_keys:
        clear_quick_approve_state(bot_key, "group", gkey)
    await approve_all_groups_cmd.finish(f"已同意 {ok} 条入群申请" + (f"，{fail} 条失败" if fail else ""))


@reject_all_groups_cmd.handle()
async def handle_reject_all_groups(bot: Bot, event: MessageEvent):
    if not await satisfies_command_permission(bot, event, "request.reject_all_groups"):
        return
    bot_key = str(bot.self_id)
    bot_pending = pending_group.get(bot_key, {})
    if not bot_pending:
        await reject_all_groups_cmd.finish("暂无待处理入群申请")
    ok, fail = 0, 0
    cleared_group_keys: set[str] = set()
    for key, req in list(bot_pending.items()):
        try:
            await bot.set_group_add_request(flag=req["flag"], sub_type="invite", approve=False)
            bot_pending.pop(key, None)
            ok += 1
            cleared_group_keys.add(key)
        except ActionFailed:
            fail += 1
            failure_cleanup_group(bot_key, key)
            cleared_group_keys.add(key)
        except Exception:
            fail += 1
    persist_pending_group(bot_key)
    for gkey in cleared_group_keys:
        clear_quick_approve_state(bot_key, "group", gkey)
    await reject_all_groups_cmd.finish(f"已拒绝 {ok} 条入群申请" + (f"，{fail} 条失败" if fail else ""))


@approve_group_cmd.handle()
async def handle_approve_group(bot: Bot, event: MessageEvent, args: Message = CommandArg()):  # noqa: B008
    if not await satisfies_command_permission(bot, event, "request.approve_group"):
        return
    arg = args.extract_plain_text().strip()
    if not arg.isdigit():
        await approve_group_cmd.finish(f"格式：{APPROVE_GROUP_COMMAND} <群号>")

    bot_key = str(bot.self_id)
    group_key = str(int(arg))
    ok, msg = await approve_group_invite_by_gid(bot, bot_key, group_key)
    if ok:
        clear_quick_approve_state(bot_key, "group", group_key)
    await approve_group_cmd.finish(msg)


@auto_accept_status_cmd.handle()
async def handle_auto_accept_status(bot: Bot, event: MessageEvent):
    if not await satisfies_command_permission(bot, event, "request.auto_accept_status"):
        return
    bot_config = BotConfig(int(bot.self_id))
    friend_on = await bot_config.auto_accept_friend()
    group_on = await bot_config.auto_accept_group()
    friend_str = "✅ 开启" if friend_on else "❌ 关闭"
    group_str = "✅ 开启" if group_on else "❌ 关闭"
    await auto_accept_status_cmd.finish(
        f"好友自动同意：{friend_str}\n入群自动同意：{group_str}\n"
        f"切换：{ENABLE_AUTO_FRIEND_COMMAND} / {DISABLE_AUTO_FRIEND_COMMAND}；"
        f"{ENABLE_AUTO_GROUP_COMMAND} / {DISABLE_AUTO_GROUP_COMMAND}"
    )


@enable_auto_friend_cmd.handle()
async def handle_enable_auto_friend(bot: Bot, event: MessageEvent):
    if not await satisfies_command_permission(bot, event, "request.enable_auto_friend"):
        return
    await BotConfig(int(bot.self_id)).set_auto_accept_friend(True)
    await enable_auto_friend_cmd.finish("已开启好友自动同意")


@disable_auto_friend_cmd.handle()
async def handle_disable_auto_friend(bot: Bot, event: MessageEvent):
    if not await satisfies_command_permission(bot, event, "request.disable_auto_friend"):
        return
    await BotConfig(int(bot.self_id)).set_auto_accept_friend(False)
    await disable_auto_friend_cmd.finish("已关闭好友自动同意")


@enable_auto_group_cmd.handle()
async def handle_enable_auto_group(bot: Bot, event: MessageEvent):
    if not await satisfies_command_permission(bot, event, "request.enable_auto_group"):
        return
    await BotConfig(int(bot.self_id)).set_auto_accept_group(True)
    await enable_auto_group_cmd.finish("已开启入群自动同意")


@disable_auto_group_cmd.handle()
async def handle_disable_auto_group(bot: Bot, event: MessageEvent):
    if not await satisfies_command_permission(bot, event, "request.disable_auto_group"):
        return
    await BotConfig(int(bot.self_id)).set_auto_accept_group(False)
    await disable_auto_group_cmd.finish("已关闭入群自动同意")


@reject_group_cmd.handle()
async def handle_reject_group(bot: Bot, event: MessageEvent, args: Message = CommandArg()):  # noqa: B008
    if not await satisfies_command_permission(bot, event, "request.reject_group"):
        return
    arg = args.extract_plain_text().strip()
    if not arg.isdigit():
        await reject_group_cmd.finish(f"格式：{REJECT_GROUP_COMMAND} <群号>")

    bot_key = str(bot.self_id)
    group_key = str(int(arg))
    ok, msg = await reject_group_invite_by_gid(bot, bot_key, group_key)
    if ok:
        clear_quick_approve_state(bot_key, "group", group_key)
    await reject_group_cmd.finish(msg)
