import asyncio
import random
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Literal

from nonebot import get_bot, logger, on_message, on_notice, on_request
from nonebot.adapters.milky import Bot, MessageSegment, permission
from nonebot.adapters.milky.event import GroupAdminChangeEvent, GroupJoinRequestEvent, GroupMessageEvent
from nonebot.permission import Permission
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule

from src.common.config import BotConfig, GroupConfig

__plugin_meta__ = PluginMetadata(
    name="牛牛轮盘",
    description="危险的轮盘游戏，参与者可能被踢出群聊或禁言，有概率炸膛哦",
    usage="""
管理员可以启动游戏：
1. 启动游戏：
    - 发送"牛牛轮盘"启动默认模式（踢人模式）
    - 发送"牛牛轮盘踢人"启动踢人模式
    - 发送"牛牛轮盘禁言"启动禁言模式
2. 参与游戏：
    - 发送"牛牛开枪"进行轮盘游戏
    - 牛牛喝酒会乱开枪哦
3. 救援功能：
    - 发送"牛牛救一下"可以解除所有禁言
    - 发送"牛牛救一下@用户"可以解除指定用户的禁言
    - 牛牛救一下有概率炸膛，喝酒后会引发特别的效果...
4. 补枪功能：
    - 发送"牛牛补一枪"可以让所有禁言延长
    - 发送"牛牛补一枪@用户"可以延长指定用户的禁言
    - 牛牛补一枪也有概率炸膛，喝酒后会引发特别的效果...
    """.strip(),
    type="application",
    homepage="https://github.com/PallasBot",
    supported_adapters={"~milky"},
    extra={
        "version": "2.0.0",
        "menu_data": [
            {
                "func": "牛牛轮盘",
                "trigger_method": "on_message",
                "trigger_condition": "牛牛轮盘/牛牛轮盘踢人/牛牛轮盘禁言",
                "brief_des": "启动轮盘",
                "detail_des": "管理员可以启动，可选择踢人模式或禁言模式。游戏开始后，六个弹槽中只有一颗子弹，触发者可能会被踢出群聊或禁言。",  # noqa: E501
            },
            {
                "func": "参与轮盘",
                "trigger_method": "on_message",
                "trigger_condition": "牛牛开枪",
                "brief_des": "参与轮盘",
                "detail_des": "在游戏进行中，参与者发送'牛牛开枪'来触发轮盘。如果命中子弹，根据游戏模式，触发者可能会被踢出群聊或禁言。",  # noqa: E501
            },
            {
                "func": "牛牛喝酒",
                "trigger_method": "on_message",
                "trigger_condition": "牛牛喝酒/牛牛干杯/牛牛继续喝",
                "brief_des": "在轮盘游戏中通过喝酒参与",
                "detail_des": "在轮盘游戏进行中，发送'牛牛喝酒'、'牛牛干杯'或'牛牛继续喝'可以参与游戏，增加被选中概率。",  # noqa: E501
            },
            {
                "func": "救援功能",
                "trigger_method": "on_message",
                "trigger_condition": "牛牛救一下",
                "brief_des": "解除被禁言的用户",
                "detail_des": "解除被禁言的用户。发送'牛牛救一下'解除所有禁言，发送'牛牛救一下@用户'解除指定用户的禁言。在牛牛喝酒以后，牛牛救一下有概率把请求的人处决了()",  # noqa: E501
            },
            {
                "func": "补枪功能",
                "trigger_method": "on_message",
                "trigger_condition": "牛牛补一枪",
                "brief_des": "延长被禁言用户的禁言时间",
                "detail_des": "延长被禁言用户的禁言时间。发送'牛牛补一枪'可以让所有禁言延长，发送'牛牛补一枪@用户'可以延长指定用户的禁言。在牛牛喝酒以后，牛牛补一枪有概率把请求的人处决了()",  # noqa: E501
            },
        ],
        "menu_template": "default",
    },
)


roulette_status = defaultdict(int)  # 0 关闭 1 开启
roulette_time = defaultdict(int)
roulette_count = defaultdict(int)
timeout = 300
roulette_player = defaultdict(list)
ban_players = defaultdict(list)
role_cache = defaultdict(lambda: defaultdict(str))

shot_lock = asyncio.Lock()


async def sync_role_cache(
    bot: Bot, event: GroupMessageEvent | GroupAdminChangeEvent
) -> Literal["owner", "admin", "member"]:
    if isinstance(event, GroupMessageEvent):
        info = await bot.get_group_member_info(user_id=event.self_id, group_id=event.data.peer_id, no_cache=True)
        role_cache[event.self_id][event.data.peer_id] = info.role
        return info.role
    else:
        info = await bot.get_group_member_info(user_id=event.self_id, group_id=event.data.group_id, no_cache=True)
        role_cache[event.self_id][event.data.group_id] = info.role
        return info.role


async def is_set_group_admin(event: GroupAdminChangeEvent) -> bool:
    if event.data.user_id == event.self_id and event.data.is_set:
        return True
    return False


set_group_admin = on_notice(
    rule=Rule(is_set_group_admin),
    permission=permission.GROUP,
    priority=3,
    block=False,
)


@set_group_admin.handle()
async def _(bot: Bot, event: GroupAdminChangeEvent):
    await sync_role_cache(bot, event)


def can_roulette_start(group_id: int) -> bool:
    if roulette_status[group_id] == 0 or time.time() - roulette_time[group_id] > timeout:
        return True

    return False


async def participate_in_roulette(event: GroupMessageEvent) -> bool:
    """
    牛牛自己是否参与轮盘
    """
    if await BotConfig(event.self_id, event.data.peer_id).drunkenness() <= 0:
        return False

    if await GroupConfig(event.data.peer_id).roulette_mode() == 1:
        # 没法禁言自己
        return False

    # 群主退不了群（除非解散），所以群主牛牛不参与游戏
    if role_cache[event.self_id][event.data.peer_id] == "owner":
        return False

    return random.random() < 0.1667


async def roulette(messagae_handle, event: GroupMessageEvent):
    rand = random.randint(1, 6)
    logger.info(f"Roulette rand: {rand}")
    roulette_status[event.data.peer_id] = rand
    roulette_count[event.data.peer_id] = 0
    roulette_time[event.data.peer_id] = int(time.time())
    ban_players[event.data.peer_id] = []
    partin = await participate_in_roulette(event)
    if partin:
        roulette_player[event.data.peer_id] = [
            event.self_id,
            event.data.sender_id,
        ]
    else:
        roulette_player[event.data.peer_id] = [
            event.data.sender_id,
        ]
    mode = await GroupConfig(event.data.peer_id).roulette_mode()
    if mode == 0:
        type_msg = "踢出群聊"
    else:
        type_msg = "禁言"
    await messagae_handle.finish(
        f"这是一把充满荣耀与死亡的左轮手枪，六个弹槽只有一颗子弹，中弹的那个人将会被{type_msg}。勇敢的战士们啊，扣动你们的扳机吧！"
    )


async def is_roulette_type_msg(bot: Bot, event: GroupMessageEvent) -> bool:
    if event.get_plaintext().strip() in {"牛牛轮盘踢人", "牛牛轮盘禁言", "牛牛踢人轮盘", "牛牛禁言轮盘"}:
        if can_roulette_start(event.data.peer_id):
            if not role_cache[event.self_id][event.data.peer_id]:
                await sync_role_cache(bot, event)
            return role_cache[event.self_id][event.data.peer_id] in {"admin", "owner"}
    return False


async def is_config_admin(event: GroupMessageEvent) -> bool:
    return await BotConfig(event.self_id).is_admin_of_bot(event.data.sender_id)


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
    mode = None
    if "踢人" in plaintext:
        mode = 0
    elif "禁言" in plaintext:
        mode = 1
    if mode is not None:
        await GroupConfig(event.data.peer_id).set_roulette_mode(mode)

    await roulette(roulette_type_msg, event)


async def is_roulette_msg(bot: Bot, event: GroupMessageEvent) -> bool:
    if event.get_plaintext().strip() == "牛牛轮盘":
        if can_roulette_start(event.data.peer_id):
            if not role_cache[event.self_id][event.data.peer_id]:
                await sync_role_cache(bot, event)
            return role_cache[event.self_id][event.data.peer_id] in {"admin", "owner"}

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
    if roulette_status[event.data.peer_id] != 0 and event.get_plaintext().strip() == "牛牛开枪":
        return role_cache[event.self_id][event.data.peer_id] in {"admin", "owner"}

    return False


kicked_users = defaultdict(set)


async def shot(self_id: int, user_id: int, group_id: int) -> Callable[[], Awaitable[None]] | None:
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
        roulette_status[event.data.peer_id] -= 1
        roulette_count[event.data.peer_id] += 1
        shot_msg_count = roulette_count[event.data.peer_id]
        roulette_time[event.data.peer_id] = int(time.time())
        roulette_player[event.data.peer_id].append(event.data.sender_id)

        if shot_msg_count == 6 and random.random() < 0.125:
            roulette_status[event.data.peer_id] = 0
            roulette_player[event.data.peer_id] = []
            await roulette_msg.finish("我的手中的这把武器，找了无数工匠都难以修缮如新。不......不该如此......")

        elif roulette_status[event.data.peer_id] > 0:
            await roulette_msg.finish(shot_text[shot_msg_count - 1] + f"( {shot_msg_count} / 6 )")

        roulette_status[event.data.peer_id] = 0

        async def let_the_bullets_fly():
            await asyncio.sleep(random.randint(5, 20))

        if await BotConfig(event.self_id, event.data.peer_id).drunkenness() <= 0:
            roulette_player[event.data.peer_id] = []
            shot_awaitable = await shot(event.self_id, event.data.sender_id, event.data.peer_id)
            if shot_awaitable:
                reply_msg = (
                    "米诺斯英雄们的故事......有喜剧，便也会有悲剧。舍弃了荣耀，"
                    + MessageSegment.mention(event.data.sender_id)
                    + MessageSegment.text("选择回归平凡......")
                )
                await roulette_msg.send(reply_msg)
                await let_the_bullets_fly()
                await shot_awaitable()
            else:
                reply_msg = "听啊，悲鸣停止了。这是幸福的和平到来前的宁静。"
                await roulette_msg.finish(reply_msg)

        else:
            player = roulette_player[event.data.peer_id]
            rand_list = player[-random.randint(1, min(len(player), 6)) :][::-1]
            roulette_player[event.data.peer_id] = []
            shot_awaitable_list = []
            for user_id in rand_list:
                shot_awaitable = await shot(event.self_id, user_id, event.data.peer_id)
                if not shot_awaitable:
                    continue

                shot_awaitable_list.append(shot_awaitable)

                reply_msg = (
                    "米诺斯英雄们的故事......有喜剧，便也会有悲剧。舍弃了荣耀，"
                    + MessageSegment.mention(user_id)
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
async def _(bot: Bot, event: GroupJoinRequestEvent):
    if event.data.initiator_id in kicked_users[event.data.group_id]:
        kicked_users[event.data.group_id].remove(event.data.initiator_id)
        await bot.accept_group_request(
            notification_seq=event.data.notification_seq, notification_type="join_request", group_id=event.data.group_id
        )


async def is_drink_msg(event: GroupMessageEvent) -> bool:
    if roulette_status[event.data.peer_id] != 0 and event.get_plaintext().strip() in {
        "牛牛喝酒",
        "牛牛干杯",
        "牛牛继续喝",
    }:
        return role_cache[event.self_id][event.data.peer_id] in {"admin", "owner"}
    return False


drink_msg = on_message(
    priority=4,
    block=False,
    rule=Rule(is_drink_msg),
    permission=permission.GROUP,
)


@drink_msg.handle()
async def _(event: GroupMessageEvent):
    roulette_player[event.data.peer_id].append(event.data.sender_id)


async def is_rescue_msg(event: GroupMessageEvent) -> bool:
    if event.get_plaintext().strip().startswith("牛牛救一下"):
        return role_cache[event.self_id][event.data.peer_id] in {"admin", "owner"}
    return False


rescue_msg = on_message(
    priority=5,
    block=True,
    rule=Rule(is_rescue_msg),
    permission=permission.GROUP,
)


@rescue_msg.handle()
async def _(bot: Bot, event: GroupMessageEvent):
    current_group_id = event.data.peer_id
    if random.random() < 0.125:
        await rescue_msg.finish("十二英雄神殿中的圣火也依然在熊熊燃烧吧，只是我再也没资格去点燃圣火了...")

    if await BotConfig(event.self_id, event.data.peer_id).drunkenness() > 0 and random.random() < 0.3:
        mode = await GroupConfig(event.data.peer_id).roulette_mode()
        if mode == 0:
            user_info = await bot.get_group_member_info(user_id=event.self_id, group_id=event.data.peer_id)
            user_role = user_info.role

            if user_role != "owner" and not (
                user_role == "admin" and role_cache[event.self_id][event.data.peer_id] != "owner"
            ):
                kicked_users[event.data.peer_id].add(event.data.sender_id)
                await bot.kick_group_member(group_id=event.data.peer_id, user_id=event.data.sender_id)
                await rescue_msg.finish("呃......咳嗯，博士，这个叫“二踢脚”的可以在我头上放吗...")
            else:
                await rescue_msg.finish("呃......咳嗯，博士，这个叫“二踢脚”的是在他头上放吗...")
        else:
            await bot.set_group_member_mute(
                group_id=event.data.peer_id,
                user_id=event.data.sender_id,
                duration=random.randint(5, 20) * 60,
            )
            ban_players[event.data.peer_id].append(event.data.sender_id)
            await rescue_msg.finish("呃......咳嗯，博士，这个叫“二踢脚”的是在他头上放吗...")
        return

    at_list = [
        msg_seg.data["qq"] for msg_seg in event.message if msg_seg.type == "at" and msg_seg.data.get("qq") != "all"
    ]
    target_user_ids = list(map(int, at_list))

    if target_user_ids:
        rescued_users = []

        for target_user_id in target_user_ids:
            try:
                await bot.set_group_member_mute(
                    group_id=current_group_id,
                    user_id=target_user_id,
                    duration=0,
                )
                rescued_users.append(target_user_id)

                if current_group_id in ban_players and target_user_id in ban_players[current_group_id]:
                    ban_players[current_group_id].remove(target_user_id)
            except Exception as e:
                logger.error(e)

        reply_segments = []

        if rescued_users:
            reply_segments.append(MessageSegment.text("命运之手指向了为沉默所困之人："))
            reply_segments.extend(MessageSegment.mention(user_id) for user_id in rescued_users)
            reply_segments.append(MessageSegment.text("，已从沉默中被解放。"))

        await rescue_msg.finish(MessageSegment.text("").join(reply_segments))

    else:
        rescued_users = []
        if current_group_id in ban_players:
            for user_id in list(ban_players[current_group_id]):
                try:
                    await bot.set_group_member_mute(
                        group_id=current_group_id,
                        user_id=user_id,
                        duration=0,
                    )
                    rescued_users.append(user_id)
                except Exception as e:
                    logger.error(e)

            ban_players[current_group_id] = []

        if rescued_users:
            await rescue_msg.finish("命运的轮盘再次转动，所有的沉默都被打破。")
        else:
            await rescue_msg.finish("此刻并无需要拯救之人，和平仍在延续。")


async def is_judgment_msg(event: GroupMessageEvent) -> bool:
    if event.get_plaintext().strip().startswith("牛牛补一枪"):
        return role_cache[event.self_id][event.group_id] in {"admin", "owner"}
    return False


judgment_msg = on_message(
    priority=5,
    block=True,
    rule=Rule(is_judgment_msg),
    permission=permission.GROUP,
)


@judgment_msg.handle()
async def _(bot: Bot, event: GroupMessageEvent):
    current_group_id = event.group_id
    if random.random() < 0.125:
        await judgment_msg.finish("我的手中的这把武器，找了无数工匠都难以修缮如新。不......不该如此......")

    if await BotConfig(event.self_id, event.group_id).drunkenness() > 0 and random.random() < 0.3:
        mode = await GroupConfig(event.group_id).roulette_mode()
        if mode == 0:
            user_info = await bot.call_api(
                "get_group_member_info",
                **{
                    "user_id": event.user_id,
                    "group_id": event.group_id,
                },
            )
            user_role = user_info["role"]

            if user_role != "owner" and not (
                user_role == "admin" and role_cache[event.self_id][event.group_id] != "owner"
            ):
                kicked_users[event.group_id].add(event.user_id)
                await bot.call_api(
                    "set_group_kick",
                    **{
                        "user_id": event.user_id,
                        "group_id": event.group_id,
                    },
                )
                await judgment_msg.finish("呃......咳嗯，博士，这个叫“二踢脚”的可以在我头上放吗...")
            else:
                await judgment_msg.finish("呃......咳嗯，博士，这个叫“二踢脚”的是在他头上放吗...")
        else:
            await bot.call_api(
                "set_group_ban",
                **{
                    "user_id": event.user_id,
                    "group_id": event.group_id,
                    "duration": random.randint(25, 120) * 60,
                },
            )
            ban_players[event.group_id].append(event.user_id)
            await judgment_msg.finish("呃......咳嗯，博士，这个叫“二踢脚”的是在他头上放吗...")
        return

    at_list = [
        msg_seg.data["qq"] for msg_seg in event.message if msg_seg.type == "at" and msg_seg.data.get("qq") != "all"
    ]
    target_user_ids = list(map(int, at_list))

    if target_user_ids:
        judgmentd_users = []

        for target_user_id in target_user_ids:
            try:
                await bot.call_api(
                    "set_group_ban",
                    **{
                        "user_id": target_user_id,
                        "group_id": current_group_id,
                        "duration": random.randint(30, 80) * 60,
                    },
                )
                judgmentd_users.append(target_user_id)

                if current_group_id in ban_players and target_user_id in ban_players[current_group_id]:
                    ban_players[current_group_id].remove(target_user_id)
            except Exception as e:
                logger.error(e)

        reply_segments = []

        if judgmentd_users:
            reply_segments.append(MessageSegment.text("	哭嚎吧，"))
            reply_segments.extend(MessageSegment.at(user_id) for user_id in judgmentd_users)
            reply_segments.append(MessageSegment.text(",为你们不堪一击的信念。"))

        await judgment_msg.finish(MessageSegment.text("").join(reply_segments))

    else:
        judgmentd_users = []
        if current_group_id in ban_players:
            for user_id in list(ban_players[current_group_id]):
                try:
                    await bot.call_api(
                        "set_group_ban",
                        **{
                            "user_id": user_id,
                            "group_id": current_group_id,
                            "duration": random.randint(20, 40) * 60,
                        },
                    )
                    judgmentd_users.append(user_id)
                except Exception as e:
                    logger.error(e)

            ban_players[current_group_id] = []

        if judgmentd_users:
            await judgment_msg.finish("是吗，我们做到了吗......我现在，正体会至高的荣誉和幸福。")
        else:
            await judgment_msg.finish("转身吧，勇士们。我们已经获得了完美的胜利，现在是该回去享受庆祝的盛典了。")
