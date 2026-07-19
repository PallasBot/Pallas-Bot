import asyncio
import random

from nonebot import get_bot, on_command, on_message, on_notice
from nonebot.adapters import Bot, Event
from nonebot.adapters.onebot.v11 import (
    FriendAddNoticeEvent,
    GroupAdminNoticeEvent,
    GroupBanNoticeEvent,
    GroupDecreaseNoticeEvent,
    GroupIncreaseNoticeEvent,
    GroupMessageEvent,
    MessageEvent,
    MessageSegment,
    PokeNotifyEvent,
    PrivateMessageEvent,
    permission,
)
from nonebot.rule import Rule, to_me
from nonebot.typing import T_State

from packages.blacklist import invalidate_group_ban_gate_cache, invalidate_user_ban_gate_cache
from pallas.core.foundation.config import BotConfig, GroupConfig, UserConfig
from pallas.core.perm import (
    group_message_permission_for_command,
    private_message_permission_for_command,
)
from pallas.core.plugin_coord.duel import duel_qte_blocks_greeting_user
from pallas.core.shared.utils import is_bot_admin
from pallas.product.ban_gate.snapshot import patch_group_banned, patch_user_banned

from .config import plugin_config
from .voice import get_random_voice, get_voice_filepath
from .welcome_storage import (
    GREETING_DIR,
    bot_dir,
    clear_group_welcome_files,
    clear_welcome_files,
    download_image,
    get_custom_friend_welcome_message,
    get_custom_group_welcome_message,
    greeting_voices,
    group_welcome_dir,
    operator,
    target_msgs,
    user_is_group_admin_or_owner,
)


async def greeting_plugin_disabled(
    group_id: int | None,
    bot_id: int | str,
    *,
    bot: Bot | None = None,
    event: Event | None = None,
) -> bool:
    from packages.help.plugin_manager import is_plugin_disabled

    return await is_plugin_disabled("greeting", group_id, int(bot_id), bot=bot, event=event)


def call_me_message_rule(event: GroupMessageEvent) -> bool:
    if event.raw_message not in target_msgs:
        return False
    return not duel_qte_blocks_greeting_user(event.group_id, event.user_id)


set_friend_welcome = on_command(
    "设置好友欢迎",
    permission=private_message_permission_for_command("greeting.set_friend_welcome"),
    priority=10,
    block=True,
)


@set_friend_welcome.handle()
async def handle_set_friend_welcome(bot: Bot, event: PrivateMessageEvent, state: T_State):
    await set_friend_welcome.send("请发送你想要设置的好友欢迎消息（可以是文本、图片或图文混合）：")
    state["bot_id"] = event.self_id


@set_friend_welcome.got("message")
async def handle_friend_welcome_message(bot: Bot, event: PrivateMessageEvent, state: T_State):
    bot_id: int = state["bot_id"]
    message = event.get_message()
    images = [seg for seg in message if seg.type == "image"]
    text_parts = [seg.data.get("text", "").strip() for seg in message if seg.type == "text"]
    text_content = "\n".join(p for p in text_parts if p)

    if not images and not text_content:
        await set_friend_welcome.reject("欢迎消息不能为空，请重新发送（可以是文本或图片）：")

    d = bot_dir(bot_id)
    clear_welcome_files(d)

    if text_content:
        (d / "friend_welcome.txt").write_text(text_content, encoding="utf-8")

    if images:
        image_url = images[0].data.get("url") or images[0].data.get("file", "")
        if not image_url:
            await set_friend_welcome.reject("无法获取图片链接，请重新发送：")
        try:
            data, ext = await download_image(image_url)
            (d / f"friend_welcome{ext}").write_bytes(data)
        except Exception as e:
            await set_friend_welcome.reject(f"图片下载失败：{e}\n请重新发送：")

    parts = []
    if text_content:
        parts.append("文本")
    if images:
        parts.append("图片")
    label = "＋".join(parts)
    await set_friend_welcome.finish(f"好友欢迎消息（{label}）已设置成功！")


clear_friend_welcome = on_command(
    "清除好友欢迎",
    permission=private_message_permission_for_command("greeting.clear_friend_welcome"),
    priority=10,
    block=True,
)


@clear_friend_welcome.handle()
async def handle_clear_friend_welcome(bot: Bot, event: PrivateMessageEvent):
    d = GREETING_DIR / str(event.self_id)
    if not d.exists():
        await clear_friend_welcome.finish("未设置自定义好友欢迎消息")

    before = list(d.glob("friend_welcome*"))
    clear_welcome_files(d)
    after = list(d.glob("friend_welcome*"))

    if len(before) > len(after):
        await clear_friend_welcome.finish("好友欢迎消息已清除！")
    else:
        await clear_friend_welcome.finish("未设置自定义好友欢迎消息")


set_group_welcome = on_command(
    "设置群欢迎",
    permission=group_message_permission_for_command("greeting.set_group_welcome"),
    priority=10,
    block=True,
)


@set_group_welcome.handle()
async def handle_set_group_welcome(bot: Bot, event: GroupMessageEvent, state: T_State):
    if not await user_is_group_admin_or_owner(event.self_id, event.group_id, event.user_id):
        await set_group_welcome.finish("只有群主或群管理员可以设置本群欢迎")
    await set_group_welcome.send("请发送你想要设置的本群入群欢迎（可以是文本、图片或图文混合）：")
    state["bot_id"] = event.self_id
    state["group_id"] = event.group_id


@set_group_welcome.got("message")
async def handle_group_welcome_message(bot: Bot, event: MessageEvent, state: T_State):
    if not isinstance(event, GroupMessageEvent):
        await set_group_welcome.reject("请在群内发送欢迎消息内容：")
    group_id: int = state["group_id"]
    if event.group_id != group_id:
        await set_group_welcome.reject("请在发起设置的同一个群内发送欢迎消息内容：")
    if not await user_is_group_admin_or_owner(event.self_id, event.group_id, event.user_id):
        await set_group_welcome.finish("只有群主或群管理员可以设置本群欢迎")

    bot_id: int = state["bot_id"]
    message = event.get_message()
    images = [seg for seg in message if seg.type == "image"]
    text_parts = [seg.data.get("text", "").strip() for seg in message if seg.type == "text"]
    text_content = "\n".join(p for p in text_parts if p)

    if not images and not text_content:
        await set_group_welcome.reject("欢迎消息不能为空，请重新发送（可以是文本或图片）：")

    d = group_welcome_dir(bot_id, group_id)
    clear_group_welcome_files(d)

    if text_content:
        (d / "group_welcome.txt").write_text(text_content, encoding="utf-8")

    if images:
        image_url = images[0].data.get("url") or images[0].data.get("file", "")
        if not image_url:
            await set_group_welcome.reject("无法获取图片链接，请重新发送：")
        try:
            data, ext = await download_image(image_url)
            (d / f"group_welcome{ext}").write_bytes(data)
        except Exception as e:
            await set_group_welcome.reject(f"图片下载失败：{e}\n请重新发送：")

    parts = []
    if text_content:
        parts.append("文本")
    if images:
        parts.append("图片")
    label = "＋".join(parts)
    await set_group_welcome.finish(f"本群入群欢迎（{label}）已设置成功！")


clear_group_welcome = on_command(
    "清除群欢迎",
    permission=group_message_permission_for_command("greeting.clear_group_welcome"),
    priority=10,
    block=True,
)


@clear_group_welcome.handle()
async def handle_clear_group_welcome(bot: Bot, event: GroupMessageEvent):
    if not await user_is_group_admin_or_owner(event.self_id, event.group_id, event.user_id):
        await clear_group_welcome.finish("只有群主或群管理员可以清除本群欢迎")

    d = GREETING_DIR / str(event.self_id) / str(event.group_id)
    if not d.exists():
        await clear_group_welcome.finish("未设置自定义本群入群欢迎")

    before = list(d.glob("group_welcome*"))
    clear_group_welcome_files(d)
    after = list(d.glob("group_welcome*"))

    if len(before) > len(after):
        await clear_group_welcome.finish("本群入群欢迎已清除！")
    else:
        await clear_group_welcome.finish("未设置自定义本群入群欢迎")


call_me_cmd = on_message(
    rule=Rule(call_me_message_rule),
    priority=1,
    block=True,
    permission=permission.GROUP,
)


@call_me_cmd.handle()
async def handle_call_me(bot: Bot, event: GroupMessageEvent):
    if await greeting_plugin_disabled(event.group_id, event.self_id, bot=bot, event=event):
        return
    config = BotConfig(event.self_id, event.group_id)
    if not await config.is_cooldown("call_me"):
        return
    await config.refresh_cooldown("call_me")

    file_path = get_random_voice(operator, greeting_voices)
    if file_path:
        voice_bytes = await asyncio.to_thread(file_path.read_bytes)
        await call_me_cmd.finish(MessageSegment.record(file=voice_bytes))


to_me_cmd = on_message(
    rule=to_me(),
    priority=14,
    block=False,
    permission=permission.GROUP,
)


@to_me_cmd.handle()
async def handle_to_me(bot: Bot, event: GroupMessageEvent):
    if await greeting_plugin_disabled(event.group_id, event.self_id, bot=bot, event=event):
        return

    config = BotConfig(event.self_id, event.group_id)
    if not await config.is_cooldown("to_me"):
        return
    await config.refresh_cooldown("to_me")

    if len(event.get_plaintext().strip()) == 0 and not event.reply:
        file_path = get_random_voice(operator, greeting_voices)
        if file_path:
            await to_me_cmd.finish(MessageSegment.record(file=file_path.read_bytes()))


all_notice = on_notice(priority=13, block=False)

_NoticeEvent = (
    GroupAdminNoticeEvent
    | GroupIncreaseNoticeEvent
    | GroupDecreaseNoticeEvent
    | GroupBanNoticeEvent
    | FriendAddNoticeEvent
    | PokeNotifyEvent
)


@all_notice.handle()
async def handle_notice(event: _NoticeEvent):
    if event.notice_type == "group_msg_emoji_like":
        return

    if await greeting_plugin_disabled(getattr(event, "group_id", None), event.self_id):
        return

    if event.notice_type == "notify" and event.sub_type == "poke" and event.target_id == event.self_id:
        config = BotConfig(event.self_id, event.group_id)  # type: ignore
        if not await config.is_cooldown("poke"):
            return
        await config.refresh_cooldown("poke")
        await asyncio.sleep(random.randint(1, 3))
        await get_bot(str(event.self_id)).call_api(
            "group_poke",
            group_id=event.group_id,
            user_id=event.user_id,
        )

    elif event.notice_type == "group_increase":
        if event.user_id == event.self_id:
            msg = (
                "我是来自米诺斯的祭司帕拉斯，会在罗德岛休息一段时间......"
                "虽然这么说，我渴望以美酒和戏剧被招待，更渴望走向战场。"
            )
        else:
            custom = await get_custom_group_welcome_message(event.self_id, event.group_id)
            if custom:
                msg = MessageSegment.at(event.user_id) + custom
            elif await is_bot_admin(event.self_id, event.group_id):
                msg = MessageSegment.at(event.user_id) + MessageSegment.text(
                    "博士，欢迎加入这盛大的庆典！我是来自米诺斯的祭司帕拉斯......要来一杯美酒么？"
                )
            else:
                return
        await all_notice.finish(msg)

    elif event.notice_type == "group_admin" and event.sub_type == "set" and event.user_id == event.self_id:
        file_path = get_voice_filepath(operator, "任命助理")
        if file_path:
            await all_notice.finish(MessageSegment.record(file=file_path.read_bytes()))

    elif event.notice_type == "friend_add":
        custom_msg = await get_custom_friend_welcome_message(event.self_id)
        if custom_msg:
            await all_notice.send(custom_msg)
        file_path = get_voice_filepath(operator, "干员报到")
        if file_path:
            await all_notice.finish(MessageSegment.record(file=file_path.read_bytes()))

    elif event.notice_type == "group_ban" and event.sub_type == "ban" and event.user_id == event.self_id:
        if event.duration > 60 * 60 * 36:
            await get_bot(str(event.self_id)).call_api("set_group_leave", group_id=event.group_id)

    elif event.notice_type == "group_decrease" and event.sub_type == "kick_me":
        if plugin_config.enable_kick_ban:
            await GroupConfig(event.group_id).ban()
            await UserConfig(event.operator_id).ban()
            await patch_group_banned(event.group_id, True)
            await patch_user_banned(event.operator_id, True)
            await invalidate_group_ban_gate_cache(event.group_id)
            await invalidate_user_ban_gate_cache(event.operator_id)
