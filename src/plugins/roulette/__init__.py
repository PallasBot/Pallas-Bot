import asyncio
import random
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable

from nonebot import get_bot, logger, on_message, on_notice, on_request
from nonebot.adapters.onebot.v11 import (
    Bot,
    GroupAdminNoticeEvent,
    GroupMessageEvent,
    GroupRequestEvent,
    MessageSegment,
    permission,
)
from nonebot.permission import Permission
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule

from src.common.config import BotConfig, GroupConfig

from .config import JUDGMENT_CFG, RESCUE_CFG, SHOT_CFG
from .player import PlayerList

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
    - 发送"牛牛救一下"可以解禁所有被牛牛禁言的玩家
    - 发送"牛牛救一下@用户"可以解除任意用户的禁言
    - 牛牛救一下有概率炸膛，喝酒后会引发特别的效果...
4. 补枪功能：
    - 发送"牛牛补一枪"可以让所有被牛牛禁言的玩家追加禁言
    - 发送"牛牛补一枪@用户"可以延长指定用户的禁言
    - 牛牛补一枪也有概率炸膛，喝酒后会引发特别的效果...
    """.strip(),
    type="application",
    homepage="https://github.com/PallasBot",
    supported_adapters={"~onebot.v11"},
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
                "func": "牛牛救一下",
                "trigger_method": "on_message",
                "trigger_condition": "牛牛救一下",
                "brief_des": "解除被禁言的用户",
                "detail_des": "解除被禁言的用户。发送'牛牛救一下'解除所有禁言，发送'牛牛救一下@用户'解除指定用户的禁言。在牛牛喝酒以后，牛牛救一下有概率把请求的人处决了()",  # noqa: E501
            },
            {
                "func": "牛牛补一枪",
                "trigger_method": "on_message",
                "trigger_condition": "牛牛补一枪",
                "brief_des": "对已禁言玩家追加惩罚",
                "detail_des": "对当前局中被禁言的玩家追加禁言时长。发送'牛牛补一枪'处理所有被禁言玩家，发送'牛牛补一枪@用户'处理指定玩家。有概率炸膛，喝酒后概率提升。",  # noqa: E501
            },
        ],
        "menu_template": "default",
    },
)


roulette_status = defaultdict(int)  # 0 关闭 1 开启
roulette_time = defaultdict(int)
roulette_count = defaultdict(int)
timeout = 300
role_cache = defaultdict(lambda: defaultdict(str))

shot_lock = asyncio.Lock()


roulette_player = PlayerList()
ban_players = PlayerList()


async def sync_role_cache(bot: Bot, event: GroupMessageEvent | GroupAdminNoticeEvent) -> str:
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


async def is_set_group_admin(event: GroupAdminNoticeEvent) -> bool:
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
    roulette_time[event.group_id] = int(time.time())
    ban_players.clear(event.group_id)
    partin = await participate_in_roulette(event)
    if partin:
        roulette_player.append(event.self_id, event.group_id)
        roulette_player.append(event.user_id, event.group_id)
    else:
        roulette_player.append(event.user_id, event.group_id)
    mode = await GroupConfig(event.group_id).roulette_mode()
    if mode == 0:
        type_msg = "踢出群聊"
    else:
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
    mode = None
    if "踢人" in plaintext:
        mode = 0
    elif "禁言" in plaintext:
        mode = 1
    if mode is not None:
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
                    "duration": SHOT_CFG.ban_duration(),
                },
            )
            ban_players.append(user_id, group_id)
            logger.info(f"用户 {user_id} 被禁言")

        return group_ban


shot_msg = on_message(
    priority=5,
    block=True,
    rule=Rule(is_shot_msg),
    permission=permission.GROUP,
)


@shot_msg.handle()
async def _(event: GroupMessageEvent):
    async with shot_lock:
        roulette_status[event.group_id] -= 1
        roulette_count[event.group_id] += 1
        shot_msg_count = roulette_count[event.group_id]
        roulette_time[event.group_id] = int(time.time())
        roulette_player.append(event.user_id, event.group_id)

        if shot_msg_count == 6 and random.random() < 0.125:
            roulette_status[event.group_id] = 0
            roulette_player.clear(event.group_id)
            await roulette_msg.finish(SHOT_CFG.misfire_msg)

        elif roulette_status[event.group_id] > 0:
            await roulette_msg.finish(SHOT_CFG.miss_texts[shot_msg_count - 1] + f"( {shot_msg_count} / 6 )")

        roulette_status[event.group_id] = 0

        async def let_the_bullets_fly():
            await asyncio.sleep(random.randint(5, 20))

        if await BotConfig(event.self_id, event.group_id).drunkenness() <= 0:
            roulette_player.clear(event.group_id)
            shot_awaitable = await shot(event.self_id, event.user_id, event.group_id)
            if shot_awaitable:
                reply_msg = (
                    MessageSegment.text(SHOT_CFG.hit_msg.split("{at}")[0])
                    + MessageSegment.at(event.user_id)
                    + MessageSegment.text(SHOT_CFG.hit_msg.split("{at}")[1])
                )
                await roulette_msg.send(reply_msg)
                await let_the_bullets_fly()
                await shot_awaitable()
            else:
                reply_msg = "听啊，悲鸣停止了。这是幸福的和平到来前的宁静。"
                await roulette_msg.finish(reply_msg)

        else:
            player_ids = roulette_player.get_user_ids(event.group_id)
            rand_list = player_ids[-random.randint(1, min(len(player_ids), 6)) :][::-1]
            roulette_player.clear(event.group_id)
            shot_awaitable_list = []
            for user_id in rand_list:
                shot_awaitable = await shot(event.self_id, user_id, event.group_id)
                if not shot_awaitable:
                    continue

                shot_awaitable_list.append(shot_awaitable)

                drunk_parts = SHOT_CFG.drunk_hit_msg.replace("{count}", str(len(shot_awaitable_list))).split("{at}")
                reply_msg = (
                    MessageSegment.text(drunk_parts[0])
                    + MessageSegment.at(user_id)
                    + MessageSegment.text(drunk_parts[1])
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
    roulette_player.append(event.user_id, event.group_id)


async def is_rescue_or_judgment(event: GroupMessageEvent) -> bool:
    """检测是否为救一下或补一枪的消息"""
    plaintext = event.get_plaintext().strip()
    if role_cache[event.self_id][event.group_id] not in {"admin", "owner"}:
        return False
    if plaintext.startswith("牛牛补一枪"):
        return len(ban_players.get_user_ids(event.group_id)) > 0
    return plaintext.startswith("牛牛救一下")


rescue_or_judgment = on_message(
    priority=4,
    block=False,
    rule=Rule(is_rescue_or_judgment),
    permission=permission.GROUP,
)


@rescue_or_judgment.handle()
async def _(bot: Bot, event: GroupMessageEvent):
    await rescue_or_judgment_handler(bot, event)


async def rescue_or_judgment_handler(bot: Bot, event: GroupMessageEvent):
    """救一下/补一枪 的统一处理函数"""
    plaintext = event.get_plaintext().strip()
    is_rescue = plaintext.startswith("牛牛救一下")
    cfg = RESCUE_CFG if is_rescue else JUDGMENT_CFG
    current_group_id = event.group_id

    if random.random() < cfg.fail_prob:
        await bot.send(event, cfg.fail_msg)
        return

    # judgment 仅在喝酒时触发，且概率独立
    is_drunk = await BotConfig(event.self_id, event.group_id).drunkenness() > 0
    if cfg.self_punish_requires_drunk and not is_drunk:
        should_punish = False
    else:
        should_punish = random.random() < cfg.self_punish_prob

    if should_punish:
        mode = await GroupConfig(event.group_id).roulette_mode()
        self_role = role_cache[event.self_id][event.group_id]
        # 群主不可被踢/禁言；牛牛不是群主时也无法操作管理员
        user_info = await bot.call_api(
            "get_group_member_info",
            user_id=event.user_id,
            group_id=event.group_id,
        )
        user_role = user_info["role"]
        is_protected = user_role == "owner" or (user_role == "admin" and self_role != "owner")

        if is_protected:
            await bot.send(event, cfg.self_punish_protected_msg)
        elif mode == 0:
            kicked_users[event.group_id].add(event.user_id)
            await bot.call_api("set_group_kick", user_id=event.user_id, group_id=event.group_id)
            await bot.send(event, cfg.self_punish_msg)
        else:
            # 牛牛是群主才能禁言管理员，否则只能禁言普通成员
            duration = cfg.self_ban_duration()
            await bot.call_api("set_group_ban", user_id=event.user_id, group_id=event.group_id, duration=duration)
            ban_players.append(event.user_id, event.group_id)
            await bot.send(event, cfg.self_punish_msg)
        return

    # @ 目标处理
    at_list = [
        msg_seg.data["qq"] for msg_seg in event.message if msg_seg.type == "at" and msg_seg.data.get("qq") != "all"
    ]
    target_user_ids = list(map(int, at_list))

    if target_user_ids:
        processed_users = []
        banned_ids = ban_players.get_user_ids(current_group_id)
        for target_user_id in target_user_ids:
            if not is_rescue and target_user_id not in banned_ids:
                continue  # 补一枪只能对本局被禁言的成员
            try:
                target_info = await bot.call_api(
                    "get_group_member_info",
                    user_id=target_user_id,
                    group_id=current_group_id,
                )
                target_role = target_info["role"]
                if target_role == "owner":
                    continue
                if target_role == "admin" and role_cache[event.self_id][current_group_id] != "owner":
                    continue
                duration = cfg.target_ban_duration()
                await bot.call_api(
                    "set_group_ban", user_id=target_user_id, group_id=current_group_id, duration=duration
                )
                processed_users.append(target_user_id)
                ban_players.find_and_refresh(target_user_id, current_group_id)
            except Exception as e:
                logger.error(e)

        if processed_users:
            reply_segments = [MessageSegment.text(cfg.target_prefix)]
            reply_segments.extend(MessageSegment.at(uid) for uid in processed_users)
            reply_segments.append(MessageSegment.text(cfg.target_suffix))
            await bot.send(event, MessageSegment.text("").join(reply_segments))
        return

    # 无@目标：对所有 ban_players 统一处理（duration=0 解禁，否则追加禁言）
    affected_users = []
    for user_id in ban_players.get_user_ids(current_group_id):
        try:
            member_info = await bot.call_api(
                "get_group_member_info",
                user_id=user_id,
                group_id=current_group_id,
            )
            member_role = member_info["role"]
            if member_role == "owner":
                continue
            if member_role == "admin" and role_cache[event.self_id][current_group_id] != "owner":
                continue
            duration = cfg.no_target_duration()
            await bot.call_api("set_group_ban", user_id=user_id, group_id=current_group_id, duration=duration)
            affected_users.append(user_id)
            ban_players.find_and_refresh(user_id, current_group_id)
        except Exception as e:
            logger.error(e)

    if is_rescue:
        ban_players.clear(current_group_id)

    if affected_users:
        await bot.send(event, cfg.no_target_msg)
    else:
        await bot.send(event, cfg.no_target_no_one_msg)
