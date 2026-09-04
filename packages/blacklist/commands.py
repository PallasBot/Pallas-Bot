from nonebot import logger, on_command
from nonebot.adapters import Bot
from nonebot.adapters.onebot.v11 import GroupMessageEvent, PrivateMessageEvent

from pallas.api.logging import format_plugin_event
from pallas.api.perm import permission_for_command
from pallas.core.foundation.config import GroupConfig, UserConfig
from pallas.product.ban_gate.snapshot import patch_group_banned, patch_group_blocked_users, patch_user_banned

from .ban_gate import invalidate_group_ban_gate_cache, invalidate_user_ban_gate_cache
from .helpers import (
    build_blacklist_view_message,
    collect_group_ids_from_plain,
    collect_target_qqs_from_plain_and_message,
)

blacklist_add_cmd = on_command(
    "牛牛拉黑",
    aliases={"牛牛屏蔽"},
    priority=5,
    block=True,
    permission=permission_for_command("blacklist.add"),
)

blacklist_remove_cmd = on_command(
    "牛牛解禁",
    aliases={"牛牛取消屏蔽", "牛牛取消拉黑"},
    priority=5,
    block=True,
    permission=permission_for_command("blacklist.remove"),
)

blacklist_add_group_cmd = on_command(
    "牛牛拉黑群",
    aliases={"牛牛屏蔽群"},
    priority=5,
    block=True,
    permission=permission_for_command("blacklist.add"),
)

blacklist_remove_group_cmd = on_command(
    "牛牛解禁群",
    aliases={"牛牛取消屏蔽群", "牛牛取消拉黑群"},
    priority=5,
    block=True,
    permission=permission_for_command("blacklist.remove"),
)

blacklist_list_cmd = on_command(
    "牛牛黑名单",
    aliases={"牛牛查看黑名单"},
    priority=5,
    block=True,
    permission=permission_for_command("blacklist.list"),
)


@blacklist_list_cmd.handle()
async def handle_blacklist_list(bot: Bot, event: GroupMessageEvent | PrivateMessageEvent):
    group_id = event.group_id if isinstance(event, GroupMessageEvent) else None
    message = await build_blacklist_view_message(group_id)
    scope = f"group [{group_id}]" if group_id is not None else "global scope"
    logger.info(format_plugin_event("list_blacklist", f"Bot [{event.self_id}] listed the blacklist for {scope}"))
    await blacklist_list_cmd.finish(message)


@blacklist_add_cmd.handle()
async def handle_blacklist_add(bot: Bot, event: GroupMessageEvent | PrivateMessageEvent):
    plain = event.get_plaintext()
    targets = collect_target_qqs_from_plain_and_message(plain, event.message)
    targets = [u for u in targets if u != event.self_id]
    if not targets:
        await blacklist_add_cmd.finish("博士，谁将失去米诺斯的眷顾？")
        return
    if isinstance(event, PrivateMessageEvent):
        for uid in targets:
            await UserConfig(uid).ban(operator=f"u:{event.user_id}")
            await patch_user_banned(uid, True)
        await invalidate_user_ban_gate_cache(targets)
        logger.info(
            format_plugin_event(
                "block_user",
                f"Bot [{event.self_id}] blocked [{len(targets)}] users globally at user [{event.user_id}]'s request",
            )
        )
        await blacklist_add_cmd.finish(
            f"米诺斯不再眷顾这 {len(targets)} 个灵魂（全局）：{', '.join(map(str, targets))}"
        )
        return
    await GroupConfig(event.group_id).add_blocked_users(targets)
    await patch_group_blocked_users(event.group_id, await GroupConfig(event.group_id).blocked_user_ids())
    await invalidate_group_ban_gate_cache(event.group_id)
    logger.info(
        format_plugin_event(
            "block_user",
            f"Bot [{event.self_id}] blocked [{len(targets)}] users in group [{event.group_id}] "
            f"at user [{event.user_id}]'s request",
        )
    )
    await blacklist_add_cmd.finish(f"在这里，米诺斯不再响应这 {len(targets)} 个灵魂：{', '.join(map(str, targets))}")


@blacklist_remove_cmd.handle()
async def handle_blacklist_remove(bot: Bot, event: GroupMessageEvent | PrivateMessageEvent):
    plain = event.get_plaintext()
    targets = collect_target_qqs_from_plain_and_message(plain, event.message)
    targets = [u for u in targets if u != event.self_id]
    if not targets:
        await blacklist_remove_cmd.finish("博士，有哪一些人又获得了米诺斯的眷顾？")
        return
    if isinstance(event, PrivateMessageEvent):
        for uid in targets:
            await UserConfig(uid).unban(operator=f"u:{event.user_id}")
            await patch_user_banned(uid, False)
        await invalidate_user_ban_gate_cache(targets)
        logger.info(
            format_plugin_event(
                "unblock_user",
                f"Bot [{event.self_id}] unblocked [{len(targets)}] users globally at user [{event.user_id}]'s request",
            )
        )
        await blacklist_remove_cmd.finish(
            f"这 {len(targets)} 个灵魂又获得了米诺斯的眷顾（全局）：{', '.join(map(str, targets))}"
        )
        return
    await GroupConfig(event.group_id).remove_blocked_users(targets)
    await patch_group_blocked_users(event.group_id, await GroupConfig(event.group_id).blocked_user_ids())
    await invalidate_group_ban_gate_cache(event.group_id)
    logger.info(
        format_plugin_event(
            "unblock_user",
            f"Bot [{event.self_id}] unblocked [{len(targets)}] users in group [{event.group_id}] "
            f"at user [{event.user_id}]'s request",
        )
    )
    await blacklist_remove_cmd.finish(f"在这里，米诺斯又愿倾听这 {len(targets)} 个灵魂：{', '.join(map(str, targets))}")


@blacklist_add_group_cmd.handle()
async def handle_blacklist_add_group(bot: Bot, event: GroupMessageEvent | PrivateMessageEvent):
    plain = event.get_plaintext()
    if isinstance(event, GroupMessageEvent):
        targets = collect_group_ids_from_plain(plain)
        if not targets:
            targets = [event.group_id]
    else:
        targets = collect_group_ids_from_plain(plain)
        if not targets:
            await blacklist_add_group_cmd.finish("博士，哪些群将失去米诺斯的眷顾？")
            return
    for gid in targets:
        await GroupConfig(gid).ban()
        await patch_group_banned(gid, True)
    await invalidate_group_ban_gate_cache(targets)
    current_group = isinstance(event, GroupMessageEvent) and targets == [event.group_id]
    log_scope = "current group" if current_group else "global"
    display_scope = "本群" if current_group else "全局"
    logger.info(
        format_plugin_event(
            "block_group",
            f"Bot [{event.self_id}] blocked [{len(targets)}] groups in {log_scope} scope "
            f"at user [{event.user_id}]'s request",
        )
    )
    await blacklist_add_group_cmd.finish(
        f"米诺斯不再眷顾这 {len(targets)} 个群聊（{display_scope}）：{', '.join(map(str, targets))}"
    )


@blacklist_remove_group_cmd.handle()
async def handle_blacklist_remove_group(bot: Bot, event: GroupMessageEvent | PrivateMessageEvent):
    plain = event.get_plaintext()
    if isinstance(event, GroupMessageEvent):
        targets = collect_group_ids_from_plain(plain)
        if not targets:
            targets = [event.group_id]
    else:
        targets = collect_group_ids_from_plain(plain)
        if not targets:
            await blacklist_remove_group_cmd.finish("博士，有哪些群又获得了米诺斯的眷顾？")
            return
    for gid in targets:
        await GroupConfig(gid).unban()
        await patch_group_banned(gid, False)
    await invalidate_group_ban_gate_cache(targets)
    current_group = isinstance(event, GroupMessageEvent) and targets == [event.group_id]
    log_scope = "current group" if current_group else "global"
    display_scope = "本群" if current_group else "全局"
    logger.info(
        format_plugin_event(
            "unblock_group",
            f"Bot [{event.self_id}] unblocked [{len(targets)}] groups in {log_scope} scope "
            f"at user [{event.user_id}]'s request",
        )
    )
    await blacklist_remove_group_cmd.finish(
        f"这 {len(targets)} 个群聊又获得了米诺斯的眷顾（{display_scope}）：{', '.join(map(str, targets))}"
    )
