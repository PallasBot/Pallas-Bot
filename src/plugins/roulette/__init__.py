import asyncio
import random
import time
from collections import defaultdict
from collections.abc import Awaitable

from nonebot import get_bot, logger, on_message, on_notice, on_request
from nonebot.adapters import Bot
from nonebot.adapters.onebot.v11 import (
    GroupAdminNoticeEvent,
    GroupMessageEvent,
    GroupRequestEvent,
    MessageSegment,
    NoticeEvent,
    permission,
)
from nonebot.permission import Permission
from nonebot.rule import Rule

from src.common.config import BotConfig, GroupConfig

roulette_status = defaultdict(int)  # 0 关闭 1 开启
roulette_time = defaultdict(int)
roulette_count = defaultdict(int)
timeout = 300
roulette_player = defaultdict(list)
ban_players = defaultdict(list)
role_cache = defaultdict(lambda: defaultdict(str))

shot_lock = asyncio.Lock()


async def sync_role_cache(bot: Bot, event: GroupMessageEvent) -> str:
    info = await bot.call_api(
        "get_group_member_info",
        **{
            "user_id": event.self_id,
            "group_id": event.group_id,
            "no_cache": True,
        },
    )
    role_cache[event.self_id][event.group_id] = info["role"]
    return info["role"]


async def is_set_group_admin(event: NoticeEvent) -> bool:
    if event.notice_type == "set_group_admin":
        if event.user_id == event.self_id:
            return True
    return False


set_group_admin = on_notice(
    rule=Rule(is_set_group_admin),
    permission=permission.GROUP,
    priority=3,
    block=False,
)


@set_group_admin.handle()
async def _(bot: Bot, event: GroupAdminNoticeEvent):
    await sync_role_cache(bot, event)


def can_roulette_start(group_id: int) -> bool:
    if roulette_status[group_id] == 0 or time.time() - roulette_time[group_id] > timeout:
        return True

    return False


async def participate_in_roulette(event: GroupMessageEvent) -> bool:
    """
    牛牛自己是否参与轮盘
    """
    if await BotConfig(event.self_id, event.group_id).drunkenness() <= 0:
        return False

    if await GroupConfig(event.group_id).roulette_mode() == 1:
        # 没法禁言自己
        return False

    # 群主退不了群（除非解散），所以群主牛牛不参与游戏
    if role_cache[event.self_id][event.group_id] == "owner":
        return False

    return random.random() < 0.1667


async def roulette(messagae_handle, event: GroupMessageEvent):
    rand = random.randint(1, 6)
    logger.info(f"Roulette rand: {rand}")
    roulette_status[event.group_id] = rand
    roulette_count[event.group_id] = 0
    roulette_time[event.group_id] = time.time()
    ban_players[event.group_id] = []
    partin = await participate_in_roulette(event)
    if partin:
        roulette_player[event.group_id] = [
            event.self_id,
            event.user_id,
        ]
    else:
        roulette_player[event.group_id] = [
            event.user_id,
        ]
    mode = await GroupConfig(event.group_id).roulette_mode()
    if mode == 0:
        type_msg = "踢出群聊"
    elif mode == 1:
        type_msg = "禁言"
    await messagae_handle.finish(
        f"这是一把充满荣耀与死亡的左轮手枪，六个弹槽只有一颗子弹，中弹的那个人将会被{type_msg}。勇敢的战士们啊，扣动你们的扳机吧！"
    )


async def is_roulette_type_msg(bot: Bot, event: GroupMessageEvent) -> bool:
    if event.get_plaintext().strip() in {"牛牛轮盘踢人", "牛牛轮盘禁言", "牛牛踢人轮盘", "牛牛禁言轮盘"}:
        if can_roulette_start(event.group_id):
            if not role_cache[event.self_id][event.group_id]:
                await sync_role_cache(bot, event)
            return role_cache[event.self_id][event.group_id] in {"admin", "owner"}
    return False


async def is_config_admin(event: GroupMessageEvent) -> bool:
    return await BotConfig(event.self_id).is_admin_of_bot(event.user_id)


IsAdmin = permission.GROUP_OWNER | permission.GROUP_ADMIN | Permission(is_config_admin)

roulette_type_msg = on_message(
    priority=5,
    block=True,
    rule=Rule(is_roulette_type_msg),
    permission=IsAdmin,
)


@roulette_type_msg.handle()
async def _(event: GroupMessageEvent):
    plaintext = event.get_plaintext().strip()
    if "踢人" in plaintext:
        mode = 0
    elif "禁言" in plaintext:
        mode = 1
    await GroupConfig(event.group_id).set_roulette_mode(mode)

    await roulette(roulette_type_msg, event)


async def is_roulette_msg(bot: Bot, event: GroupMessageEvent) -> bool:
    if event.get_plaintext().strip() == "牛牛轮盘":
        if can_roulette_start(event.group_id):
            if not role_cache[event.self_id][event.group_id]:
                await sync_role_cache(bot, event)
            return role_cache[event.self_id][event.group_id] in {"admin", "owner"}

    return False


roulette_msg = on_message(
    priority=5,
    block=True,
    rule=Rule(is_roulette_msg),
    permission=permission.GROUP,
)


@roulette_msg.handle()
async def _(event: GroupMessageEvent):
    await roulette(roulette_msg, event)


async def is_shot_msg(event: GroupMessageEvent) -> bool:
    if roulette_status[event.group_id] != 0 and event.get_plaintext().strip() == "牛牛开枪":
        return role_cache[event.self_id][event.group_id] in {"admin", "owner"}

    return False


kicked_users = defaultdict(set)


async def shot(self_id: int, user_id: int, group_id: int) -> Awaitable[None] | None:
    mode = await GroupConfig(group_id).roulette_mode()
    self_role = role_cache[self_id][group_id]

    if self_id == user_id:
        if mode == 0:  # 踢人
            if self_role == "owner":  # 牛牛是群主不能退群，不然群就解散了
                return None

            async def group_leave() -> None:
                await get_bot(str(self_id)).call_api(
                    "set_group_leave",
                    **{
                        "group_id": group_id,
                    },
                )

            return group_leave
        elif mode == 1:  # 牛牛没法禁言自己
            return None

    user_info = await get_bot(str(self_id)).call_api(
        "get_group_member_info",
        **{
            "user_id": user_id,
            "group_id": group_id,
        },
    )
    user_role = user_info["role"]

    if user_role == "owner":
        return None
    elif user_role == "admin" and self_role != "owner":
        return None

    if mode == 0:  # 踢人

        async def group_kick():
            kicked_users[group_id].add(user_id)
            await get_bot(str(self_id)).call_api(
                "set_group_kick",
                **{
                    "user_id": user_id,
                    "group_id": group_id,
                },
            )

        return group_kick

    elif mode == 1:  # 禁言

        async def group_ban():
            await get_bot(str(self_id)).call_api(
                "set_group_ban",
                **{
                    "user_id": user_id,
                    "group_id": group_id,
                    "duration": random.randint(5, 20) * 60,
                },
            )
            ban_players[group_id].append(user_id)
            logger.info(f"用户 {user_id} 被禁言")

        return group_ban


shot_msg = on_message(
    priority=5,
    block=True,
    rule=Rule(is_shot_msg),
    permission=permission.GROUP,
)

shot_text = [
    "无需退路。",
    "英雄们啊，为这最强大的信念，请站在我们这边。",
    "颤抖吧，在真正的勇敢面前。",
    "哭嚎吧，为你们不堪一击的信念。",
    "现在可没有后悔的余地了。",
    "你将在此跪拜。",
]


@shot_msg.handle()
async def _(event: GroupMessageEvent):
    async with shot_lock:
        roulette_status[event.group_id] -= 1
        roulette_count[event.group_id] += 1
        shot_msg_count = roulette_count[event.group_id]
        roulette_time[event.group_id] = time.time()
        roulette_player[event.group_id].append(event.user_id)

        if shot_msg_count == 6 and random.random() < 0.125:
            roulette_status[event.group_id] = 0
            roulette_player[event.group_id] = []
            await roulette_msg.finish("我的手中的这把武器，找了无数工匠都难以修缮如新。不......不该如此......")

        elif roulette_status[event.group_id] > 0:
            await roulette_msg.finish(shot_text[shot_msg_count - 1] + f"( {shot_msg_count} / 6 )")

        roulette_status[event.group_id] = 0

        async def let_the_bullets_fly():
            await asyncio.sleep(random.randint(5, 20))

        if await BotConfig(event.self_id, event.group_id).drunkenness() <= 0:
            roulette_player[event.group_id] = []
            shot_awaitable = await shot(event.self_id, event.user_id, event.group_id)
            if shot_awaitable:
                reply_msg = (
                    MessageSegment.text("米诺斯英雄们的故事......有喜剧，便也会有悲剧。舍弃了荣耀，")
                    + MessageSegment.at(event.user_id)
                    + MessageSegment.text("选择回归平凡......")
                )
                await roulette_msg.send(reply_msg)
                await let_the_bullets_fly()
                await shot_awaitable()
            else:
                reply_msg = "听啊，悲鸣停止了。这是幸福的和平到来前的宁静。"
                await roulette_msg.finish(reply_msg)

        else:
            player = roulette_player[event.group_id]
            rand_list = player[-random.randint(1, min(len(player), 6)) :][::-1]
            roulette_player[event.group_id] = []
            shot_awaitable_list = []
            for user_id in rand_list:
                shot_awaitable = await shot(event.self_id, user_id, event.group_id)
                if not shot_awaitable:
                    continue

                shot_awaitable_list.append(shot_awaitable)

                reply_msg = (
                    MessageSegment.text("米诺斯英雄们的故事......有喜剧，便也会有悲剧。舍弃了荣耀，")
                    + MessageSegment.at(user_id)
                    + MessageSegment.text(f"选择回归平凡...... ( {len(shot_awaitable_list)} / 6 )")
                )
                await roulette_msg.send(reply_msg)

            if not shot_awaitable_list:
                return

            await let_the_bullets_fly()
            for shot_awaitable in shot_awaitable_list:
                await shot_awaitable()


request_cmd = on_request(
    priority=15,
    block=False,
)


@request_cmd.handle()
async def _(bot: Bot, event: GroupRequestEvent):
    if event.sub_type == "add" and event.user_id in kicked_users[event.group_id]:
        kicked_users[event.group_id].remove(event.user_id)
        await event.approve(bot)


async def is_drink_msg(event: GroupMessageEvent) -> bool:
    if roulette_status[event.group_id] != 0 and event.get_plaintext().strip() in {"牛牛喝酒", "牛牛干杯", "牛牛继续喝"}:
        return role_cache[event.self_id][event.group_id] in {"admin", "owner"}
    return False


drink_msg = on_message(
    priority=4,
    block=False,
    rule=Rule(is_drink_msg),
    permission=permission.GROUP,
)


@drink_msg.handle()
async def _(event: GroupMessageEvent):
    roulette_player[event.group_id].append(event.user_id)


async def is_rescue_msg(event: GroupMessageEvent) -> bool:
    if event.get_plaintext().strip().startswith("牛牛救一下"):
        return role_cache[event.self_id][event.group_id] in {"admin", "owner"}  # 只给群主和管理权限
    return False


rescue_msg = on_message(
    priority=5,
    block=True,
    rule=Rule(is_rescue_msg),
    permission=permission.GROUP,
)


@rescue_msg.handle()
async def _(bot: Bot, event: GroupMessageEvent):
    current_group_id = event.group_id

    at_list = [
        msg_seg.data["qq"] for msg_seg in event.message if msg_seg.type == "at" and msg_seg.data.get("qq") != "all"
    ]
    target_user_ids = list(map(int, at_list))

    if target_user_ids:
        rescued_users = []

        for target_user_id in target_user_ids:
            try:
                await bot.call_api(
                    "set_group_ban",
                    **{
                        "user_id": target_user_id,
                        "group_id": current_group_id,
                        "duration": 0,
                    },
                )
                rescued_users.append(target_user_id)

                if current_group_id in ban_players and target_user_id in ban_players[current_group_id]:
                    ban_players[current_group_id].remove(target_user_id)
            except Exception as e:
                logger.error(e)

        reply_segments = []

        if rescued_users:
            reply_segments.append(MessageSegment.text("命运之手指向了为沉默所困之人："))
            reply_segments.extend(MessageSegment.at(user_id) for user_id in rescued_users)
            reply_segments.append(MessageSegment.text("，已从沉默中被解放。"))

        await rescue_msg.finish(MessageSegment.text("").join(reply_segments))

    else:
        rescued_users = []
        if current_group_id in ban_players:
            for user_id in list(ban_players[current_group_id]):
                try:
                    await bot.call_api(
                        "set_group_ban",
                        **{
                            "user_id": user_id,
                            "group_id": current_group_id,
                            "duration": 0,
                        },
                    )
                    rescued_users.append(user_id)
                except Exception as e:
                    logger.error(e)

            ban_players[current_group_id] = []

        if rescued_users:
            await rescue_msg.finish("命运的轮盘再次转动，所有的沉默都被打破。")
        else:
            await rescue_msg.finish("此刻并无需要拯救之人，和平仍在延续。")
