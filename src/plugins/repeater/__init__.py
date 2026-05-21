import asyncio
import random
import re
import time
from collections import defaultdict, deque

from nonebot import get_bot, get_driver, logger, on_message, on_notice
from nonebot.adapters import Bot
from nonebot.adapters.onebot.v11 import GroupMessageEvent, GroupRecallNoticeEvent, Message, MessageSegment, permission
from nonebot.exception import ActionFailed
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule, keyword, to_me
from nonebot.typing import T_State
from nonebot_plugin_apscheduler import scheduler

from src.common.bot_runtime.send_unavailable import BOT_SEND_UNAVAILABLE_ERRORS, log_bot_send_unavailable
from src.common.cmd_perm import group_message_permission_for_command
from src.common.cmd_perm.metadata_defaults import (
    PLUGIN_EXTRA_VERSION,
    PLUGIN_HOMEPAGE,
    PLUGIN_MENU_TEMPLATE,
)
from src.common.cmd_perm.metadata_text import SCENE_AUTO, SCENE_GROUP, join_usage, usage_line
from src.common.config import BotConfig
from src.common.message_scrub import is_message_scrub_blocked_async
from src.common.message_scrub.log_preview import scrub_intercept_log_preview
from src.common.multi_bot.dedup import (
    normalize_group_raw_message as _normalize_group_raw_message,
)
from src.common.multi_bot.dedup import (
    should_skip_duplicate_group_event as _should_skip_duplicate_group_event,
)
from src.common.utils.array2cqcode import try_convert_to_cqcode
from src.common.utils.media_cache import get_image, insert_image
from src.plugins.dream.ban_ack_state import DREAM_BAN_ACK_SENT_STATE_KEY

from .ban_state import REPEATER_BAN_ACK_SENT_STATE_KEY
from .emoji_reaction import reaction_msg
from .learn_queue import bind_repeater_learn_lifecycle, enqueue_repeater_learn
from .model import Chat

bind_repeater_learn_lifecycle()

__plugin_meta__ = PluginMetadata(
    name="牛牛复读",
    description="学习群聊并智能回复、跟复读与表情回应。",
    usage=join_usage(
        usage_line("群内聊天", "被动学习后回复、跟复读、定时发言"),
        usage_line("@牛牛 回复「不可以」 / 不可以发这个", "禁用指定内容"),
    ),
    type="application",
    homepage=PLUGIN_HOMEPAGE,
    supported_adapters={"~onebot.v11"},
    extra={
        "version": PLUGIN_EXTRA_VERSION,
        "menu_template": PLUGIN_MENU_TEMPLATE,
        "command_permissions": [
            {"id": "repeater.ban", "label": "复读「不可以」", "default": "staff"},
            {"id": "repeater.ban_latest", "label": "复读「不可以发这个」", "default": "staff"},
        ],
        "menu_data": [
            {
                "func": "智能回复",
                "trigger_method": "on_message",
                "trigger_scene": SCENE_AUTO,
                "trigger_condition": "群内正常聊天",
                "brief_des": "学习话题后参与讨论",
                "detail_des": "根据相似度与上下文自动回复；相同句连发多次时会跟复读。",
            },
            {
                "func": "主动发言",
                "trigger_method": "scheduler",
                "trigger_scene": SCENE_AUTO,
                "trigger_condition": "定时触发",
                "brief_des": "偶尔主动插话",
                "detail_des": "按概率用学到的话在群内发言。",
            },
            {
                "func": "表情回应",
                "trigger_method": "on_message",
                "trigger_scene": SCENE_AUTO,
                "trigger_condition": "群内消息或他人贴表情",
                "brief_des": "随机或跟随贴表情",
                "detail_des": "可对消息概率回应、对含表情消息回应，或跟随他人已贴的表情。",
            },
            {
                "func": "不可以",
                "trigger_method": "on_message",
                "trigger_scene": SCENE_GROUP,
                "trigger_condition": "@牛牛 回复「不可以」/ 不可以发这个",
                "command_permissions": ["repeater.ban", "repeater.ban_latest"],
                "brief_des": "禁止牛牛再学/再说某内容",
                "detail_des": (
                    "回复目标消息说「不可以」；或「不可以发这个」针对你上一条回复。撤回牛牛消息也会禁用该条。"
                ),
            },
        ],
    },
)
message_id_lock = asyncio.Lock()
message_id_dict = defaultdict(lambda: deque(maxlen=100))

driver = get_driver()


@driver.on_startup
async def startup():
    await Chat.update_global_blacklist()


@driver.on_shutdown
async def shutdown():
    try:
        await Chat.sync()
    except Exception:
        pass


async def is_shutup(self_id: int, group_id: int) -> bool:
    info = await get_bot(str(self_id)).call_api(
        "get_group_member_info",
        **{
            "user_id": self_id,
            "group_id": group_id,
        },
    )
    flag: bool = info["shut_up_timestamp"] > time.time()

    logger.info(f"bot [{self_id}] in group [{group_id}] is shutup: {flag}")

    return flag


async def post_proc(message: Message, self_id: int, group_id: int) -> Message:
    new_msg = Message()
    for seg in message:
        if seg.type == "at":
            try:
                info = await get_bot(str(self_id)).call_api(
                    "get_group_member_info",
                    **{
                        "user_id": seg.data["qq"],
                        "group_id": group_id,
                    },
                )
            except ActionFailed:  # 群员不存在
                continue
            nick_name = info["card"] or info["nickname"]
            new_msg += f"@{nick_name}"
        elif seg.type == "image":
            cq_code = str(seg)
            base64_data = await get_image(cq_code)
            if base64_data:
                new_msg += MessageSegment.image(file=base64_data)
            else:
                new_msg += seg
        else:
            new_msg += seg

    if not await Chat.reply_post_proc(str(message), str(new_msg), self_id, group_id):
        logger.warning(
            f"bot [{self_id}] post_proc failed in group [{group_id}]: [{str(message)[:30]}] -> [{str(new_msg)[:30]}]"
        )

    return new_msg


any_msg = on_message(
    priority=15,
    block=False,
    permission=permission.GROUP,
)


@any_msg.handle()
async def _(bot: Bot, event: GroupMessageEvent):
    # 多账号登陆，且在同一群中时；避免一条消息被处理多次
    async with message_id_lock:
        message_id = event.message_id
        group_id = event.group_id
        if group_id not in message_id_dict:
            message_id_dict[group_id] = deque(maxlen=100)
        if message_id in message_id_dict[group_id]:
            return
        message_id_dict[group_id].append(message_id)

    norm_raw = _normalize_group_raw_message(event.raw_message)
    if await _should_skip_duplicate_group_event(event.group_id, event.user_id, norm_raw, event.time):
        return

    if await is_message_scrub_blocked_async(plain_text=event.get_plaintext(), raw_message=norm_raw):
        pv = scrub_intercept_log_preview(event.get_plaintext(), norm_raw)
        logger.info(
            f"bot [{event.self_id}] repeater capture skipped (message_scrub) in group [{event.group_id}] "
            f"user [{event.user_id}] msg_id [{event.message_id}] preview [{pv}]"
        )
        return

    chat: Chat = Chat(event)

    answers = None
    config = BotConfig(event.self_id, event.group_id)
    if await config.is_cooldown("repeat"):
        answers = await chat.answer()

    for seg in event.message:
        if seg.type == "image":
            await insert_image(seg)

    await enqueue_repeater_learn(chat, event)

    if not answers:
        return

    await config.refresh_cooldown("repeat")
    delay = random.randint(2, 5)
    async for item in answers:
        msg = await post_proc(item, event.self_id, event.group_id)
        logger.info(f"bot [{event.self_id}] ready to send [{str(msg)[:30]}] to group [{event.group_id}]")

        await asyncio.sleep(delay)
        await config.refresh_cooldown("repeat")
        try:
            await any_msg.send(msg)
        except BOT_SEND_UNAVAILABLE_ERRORS as e:
            log_bot_send_unavailable(
                e,
                context="repeater",
                bot=event.self_id,
                group=event.group_id,
            )
            return
        except ActionFailed:
            if not await BotConfig(event.self_id).security():
                continue

            # 自动删除失效消息。若 bot 处于风控期，请勿开启该功能
            shutup = await is_shutup(event.self_id, event.group_id)
            if not shutup:  # 说明这条消息失效了
                logger.info(f"bot [{event.self_id}] ready to ban [{str(item)}] in group [{event.group_id}]")
                await Chat.ban(event.group_id, event.self_id, str(item), "ActionFailed")
                break
        delay = random.randint(1, 3)


async def is_reply(event: GroupMessageEvent) -> bool:
    return bool(event.reply)


ban_msg = on_message(
    rule=to_me() & keyword("不可以") & Rule(is_reply),
    priority=5,
    block=True,
    permission=group_message_permission_for_command("repeater.ban"),
)


@ban_msg.handle()
async def _(bot: Bot, event: GroupMessageEvent, state: T_State):
    if "[CQ:reply," not in try_convert_to_cqcode(event.raw_message):
        return False

    raw_message = ""
    for item in event.reply.message:  # type: ignore
        raw_reply = str(item)
        # 去掉图片消息中的 url, subType 等字段
        raw_message += re.sub(r"(\[CQ\:.+)(?:,url=*)(\])", r"\1\2", raw_reply)

    logger.info(f"bot [{event.self_id}] ready to ban [{raw_message}] in group [{event.group_id}]")

    try:
        await bot.delete_msg(message_id=event.reply.message_id)  # type: ignore
    except ActionFailed:
        logger.warning(f"bot [{event.self_id}] failed to delete [{raw_message}] in group [{event.group_id}]")

    banned = await Chat.ban(event.group_id, event.self_id, raw_message, str(event.user_id))
    if banned:
        if not state.get(DREAM_BAN_ACK_SENT_STATE_KEY):
            state[REPEATER_BAN_ACK_SENT_STATE_KEY] = True
            await ban_msg.finish("这对角可能会不小心撞倒些家具，我会尽量小心。")
    elif not state.get(DREAM_BAN_ACK_SENT_STATE_KEY):
        pass


async def is_admin_recall_self_msg(bot: Bot, event: GroupRecallNoticeEvent):
    # 好像不需要这句
    # if event.notice_type != "group_recall":
    #     return False
    self_id = event.self_id
    user_id = event.user_id
    group_id = event.group_id
    operator_id = event.operator_id
    if self_id != user_id:
        return False
    # 如果是自己撤回的就不用管
    if operator_id == self_id:
        return False
    operator_info = await bot.get_group_member_info(group_id=group_id, user_id=operator_id)
    return operator_info["role"] == "owner" or operator_info["role"] == "admin"


ban_recalled_msg = on_notice(
    rule=Rule(is_admin_recall_self_msg),
    priority=5,
    block=True,
)


@ban_recalled_msg.handle()
async def _(bot: Bot, event: GroupRecallNoticeEvent, state: T_State):
    try:
        msg = await bot.get_msg(message_id=event.message_id)
    except ActionFailed:
        logger.warning(f"bot [{event.self_id}] failed to get msg [{event.message_id}]")
        return

    raw_message = ""
    # 使用get_msg得到的消息不是消息序列，使用正则生成一个迭代对象
    for item in re.compile(r"\[[^\]]*\]|\w+").findall(try_convert_to_cqcode(msg["message"])):
        raw_reply = str(item)
        # 去掉图片消息中的 url, subType 等字段
        raw_message += re.sub(r"(\[CQ\:.+)(?:,url=*)(\])", r"\1\2", raw_reply)

    logger.info(f"bot [{event.self_id}] ready to ban [{raw_message}] in group [{event.group_id}]")

    banned = await Chat.ban(event.group_id, event.self_id, raw_message, str(f"recall by {event.operator_id}"))
    if banned:
        if not state.get(DREAM_BAN_ACK_SENT_STATE_KEY):
            state[REPEATER_BAN_ACK_SENT_STATE_KEY] = True
            await ban_recalled_msg.finish("这对角可能会不小心撞倒些家具，我会尽量小心。")
    elif not state.get(DREAM_BAN_ACK_SENT_STATE_KEY):
        pass


async def message_is_ban(bot: Bot, event: GroupMessageEvent, state: T_State) -> bool:
    return event.get_plaintext().strip() == "不可以发这个"


ban_msg_latest = on_message(
    rule=to_me() & Rule(message_is_ban),
    priority=5,
    block=True,
    permission=group_message_permission_for_command("repeater.ban_latest"),
)


@ban_msg_latest.handle()
async def _(bot: Bot, event: GroupMessageEvent, state: T_State):
    logger.info(f"bot [{event.self_id}] ready to ban latest reply in group [{event.group_id}]")

    try:
        await bot.delete_msg(message_id=event.reply.message_id)  # type: ignore
    except ActionFailed:
        logger.warning(
            f"bot [{event.self_id}] failed to delete latest reply [{event.raw_message}] in group [{event.group_id}]"
        )

    if await Chat.ban(event.group_id, event.self_id, "", str(event.user_id)):
        await ban_msg_latest.finish("这对角可能会不小心撞倒些家具，我会尽量小心。")


@scheduler.scheduled_job("interval", seconds=60)
async def speak_up():
    ret = await Chat.speak()
    if not ret:
        return

    bot_id, group_id, messages, target_id = ret

    for msg in messages:
        logger.info(f"bot [{bot_id}] ready to speak [{msg}] to group [{group_id}]")
        await get_bot(str(bot_id)).call_api(
            "send_group_msg",
            **{
                "message": msg,
                "group_id": group_id,
            },
        )
        if target_id:
            await get_bot(str(bot_id)).call_api(
                "group_poke",
                **{
                    "user_id": target_id,
                    "group_id": group_id,
                },
            )
        await asyncio.sleep(random.randint(2, 5))


@scheduler.scheduled_job("cron", hour=4)
async def update_data():
    await Chat.sync()
    await Chat.clearup_context()
