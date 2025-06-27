import asyncio
import random

from nonebot import get_bot, on_message, on_notice
from nonebot.adapters import Bot
from nonebot.adapters.onebot.v11 import (
    FriendAddNoticeEvent,
    GroupAdminNoticeEvent,
    GroupBanNoticeEvent,
    GroupDecreaseNoticeEvent,
    GroupIncreaseNoticeEvent,
    GroupMessageEvent,
    Message,
    MessageSegment,
    PokeNotifyEvent,
    permission,
)
from nonebot.rule import Rule, to_me
from nonebot.typing import T_State

from src.common.config import BotConfig, GroupConfig, UserConfig
from src.common.utils import is_bot_admin

from .voice import get_random_voice, get_voice_filepath

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
    raw_msg = event.raw_message
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
async def handle_call_me_first_receive(bot: Bot, event: GroupMessageEvent, state: T_State):
    config = BotConfig(event.self_id, event.group_id)
    if not await config.is_cooldown("call_me"):
        return
    await config.refresh_cooldown("call_me")

    msg: Message = MessageSegment.record(file=get_random_voice(operator, greeting_voices).read_bytes())
    await call_me_cmd.finish(msg)


to_me_cmd = on_message(
    rule=to_me(),
    priority=14,
    block=False,
    permission=permission.GROUP,
)


@to_me_cmd.handle()
async def handle_to_me_first_receive(bot: Bot, event: GroupMessageEvent, state: T_State):
    config = BotConfig(event.self_id, event.group_id)
    if not await config.is_cooldown("to_me"):
        return
    await config.refresh_cooldown("to_me")

    if len(event.get_plaintext().strip()) == 0 and not event.reply:
        msg: Message = MessageSegment.record(file=get_random_voice(operator, greeting_voices).read_bytes())
        await to_me_cmd.finish(msg)


all_notice = on_notice(
    priority=13,
    block=False,
)


@all_notice.handle()
async def handle_first_receive(
    event: GroupAdminNoticeEvent
    | GroupIncreaseNoticeEvent
    | GroupDecreaseNoticeEvent
    | GroupBanNoticeEvent
    | FriendAddNoticeEvent
    | PokeNotifyEvent,
):
    if event.notice_type == "notify" and event.sub_type == "poke" and event.target_id == event.self_id:
        config = BotConfig(event.self_id, event.group_id)
        if not await config.is_cooldown("poke"):
            return
        await config.refresh_cooldown("poke")

        delay = random.randint(1, 3)
        await asyncio.sleep(delay)
        await config.refresh_cooldown("poke")

        await get_bot(str(event.self_id)).call_api(
            "group_poke",
            **{
                "group_id": event.group_id,
                "user_id": event.user_id,
            },
        )

    elif event.notice_type == "group_increase":
        if event.user_id == event.self_id:
            msg = "我是来自米诺斯的祭司帕拉斯，会在罗德岛休息一段时间......虽然这么说，我渴望以美酒和戏剧被招待，更渴望走向战场。"  # noqa: E501
        elif await is_bot_admin(event.self_id, event.group_id):
            msg: Message = MessageSegment.at(event.user_id) + MessageSegment.text(
                "博士，欢迎加入这盛大的庆典！我是来自米诺斯的祭司帕拉斯......要来一杯美酒么？"
            )
        else:
            return
        await all_notice.finish(msg)

    elif event.notice_type == "group_admin" and event.sub_type == "set" and event.user_id == event.self_id:
        msg: Message = MessageSegment.record(file=get_voice_filepath(operator, "任命助理").read_bytes())
        await all_notice.finish(msg)

    elif event.notice_type == "friend_add":
        msg: Message = MessageSegment.record(file=get_voice_filepath(operator, "精英化晋升2").read_bytes())
        await all_notice.finish(msg)

    # 单次被禁言超过 36 小时自动退群
    elif event.notice_type == "group_ban" and event.sub_type == "ban" and event.user_id == event.self_id:
        if event.duration > 60 * 60 * 36:
            await get_bot(str(event.self_id)).call_api(
                "set_group_leave",
                **{
                    "group_id": event.group_id,
                },
            )

    # 被踢了拉黑该群（所以拉黑了又能做什么呢）
    elif event.notice_type == "group_decrease" and event.sub_type == "kick_me":
        await GroupConfig(event.group_id).ban()
        await UserConfig(event.operator_id).ban()
