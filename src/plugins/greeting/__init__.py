import asyncio
import random

from nonebot import get_plugin_config, on_message, on_notice
from nonebot.adapters.milky import Bot, MessageSegment, permission
from nonebot.adapters.milky.event import (
    GroupAdminChangeEvent,
    GroupMemberDecreaseEvent,
    GroupMemberIncreaseEvent,
    GroupMessageEvent,
    GroupMuteEvent,
    GroupNudgeEvent,
)
from nonebot.rule import Rule, is_type, to_me

from src.common.config import BotConfig, GroupConfig, UserConfig
from src.common.utils import is_bot_admin

from .config import Config
from .voice import get_random_voice, get_voice_filepath

plugin_config = get_plugin_config(Config)

operator = "Pallas"
greeting_voices = [
    "交谈1",
    "交谈2",
    "交谈3",
    "晋升后交谈1",
    "晋升后交谈2",
    "信赖提升后交谈1",
    "信赖提升后交谈2",
    "信赖提升后交谈3",
    "闲置",
    "干员报到",
    "精英化晋升1",
    "编入队伍",
    "任命队长",
    "戳一下",
    "信赖触摸",
    "问候",
]

# 请下载 https://huggingface.co/pallasbot/Pallas-Bot/blob/main/voices.zip
# 解压放到 resource/ 文件夹下

target_msgs = {"牛牛", "帕拉斯"}


async def message_equal(event: GroupMessageEvent) -> bool:
    raw_msg = str(event.data.message)
    for target in target_msgs:
        if target == raw_msg:
            return True
    return False


call_me_cmd = on_message(
    rule=Rule(message_equal),
    priority=13,
    block=False,
    permission=permission.GROUP,
)


@call_me_cmd.handle()
async def handle_call_me_first_receive(event: GroupMessageEvent):
    config = BotConfig(event.self_id, event.data.peer_id)
    if not await config.is_cooldown("call_me"):
        return
    await config.refresh_cooldown("call_me")

    file_path = get_random_voice(operator, greeting_voices)
    if not file_path:
        await call_me_cmd.finish()

    msg = MessageSegment.record(path=file_path)
    await call_me_cmd.finish(msg)


to_me_cmd = on_message(
    rule=to_me(),
    permission=permission.GROUP,
    priority=14,
    block=False,
)


@to_me_cmd.handle()
async def handle_to_me_first_receive(event: GroupMessageEvent):
    config = BotConfig(event.self_id, event.data.peer_id)
    if not await config.is_cooldown("to_me"):
        return
    await config.refresh_cooldown("to_me")

    if len(event.get_plaintext().strip()) == 0 and not event.reply:
        file_path = get_random_voice(operator, greeting_voices)
        if not file_path:
            await to_me_cmd.finish()
        msg = MessageSegment.record(path=file_path)
        await to_me_cmd.finish(msg)


nudge_notice = on_notice(
    rule=Rule(is_type(GroupNudgeEvent)),
    priority=13,
    block=False,
)


@nudge_notice.handle()
async def handle_nudge(bot: Bot, event: GroupNudgeEvent):
    if event.data.receiver_id != event.self_id or event.data.sender_id == event.self_id:
        return
    config = BotConfig(event.self_id, event.data.group_id)
    if not await config.is_cooldown("nudge"):
        return
    await config.refresh_cooldown("nudge")

    delay = random.randint(1, 3)
    await asyncio.sleep(delay)
    await config.refresh_cooldown("nudge")

    await bot.send_group_nudge(
        group_id=event.data.group_id,
        user_id=event.data.sender_id,
    )


group_increase_notice = on_notice(
    rule=Rule(is_type(GroupMemberIncreaseEvent)),
    priority=13,
    block=False,
)


@group_increase_notice.handle()
async def handle_group_increase(event: GroupMemberIncreaseEvent):
    if event.data.user_id == event.self_id:
        msg = "我是来自米诺斯的祭司帕拉斯，会在罗德岛休息一段时间......虽然这么说，我渴望以美酒和戏剧被招待，更渴望走向战场。"  # noqa: E501
    elif await is_bot_admin(event.self_id, event.data.group_id):
        msg = (
            MessageSegment.mention(event.data.user_id)
            + "博士，欢迎加入这盛大的庆典！我是来自米诺斯的祭司帕拉斯......要来一杯美酒么？"
        )
    else:
        return
    await group_increase_notice.finish(message=msg)


group_admin_change_notice = on_notice(
    rule=Rule(is_type(GroupAdminChangeEvent)),
    priority=13,
    block=False,
)


@group_admin_change_notice.handle()
async def handle_group_admin_change(event: GroupAdminChangeEvent):
    if event.data.user_id != event.self_id or not event.data.is_set:
        return
    file_path = get_voice_filepath(operator, "任命助理")
    if not file_path:
        await group_admin_change_notice.finish()
    msg = MessageSegment.record(path=file_path)
    await group_admin_change_notice.finish(msg)


group_mute_notice = on_notice(
    rule=Rule(is_type(GroupMuteEvent)),
    priority=13,
    block=False,
)


@group_mute_notice.handle()
async def handle_group_mute(bot: Bot, event: GroupMuteEvent):
    if event.data.user_id != event.self_id or event.data.duration <= 60 * 60 * 36:
        return
    await bot.quit_group(group_id=event.data.group_id)


group_decrease_notice = on_notice(
    rule=Rule(is_type(GroupMemberDecreaseEvent)),
    priority=13,
    block=False,
)


@group_decrease_notice.handle()
async def handle_group_decrease(event: GroupMemberDecreaseEvent):
    if event.data.user_id != event.self_id or event.data.operator_id == event.self_id or event.data.operator_id is None:
        return
    if plugin_config.enable_kick_ban:
        await GroupConfig(event.data.group_id).ban()
        await UserConfig(event.data.operator_id).ban()
