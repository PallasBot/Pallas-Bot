import re

from nonebot import on_message
from nonebot.adapters import Bot
from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageSegment, permission
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule
from nonebot.typing import T_State

from src.common.cmd_perm import group_message_permission_for_command
from src.common.config import BotConfig
from src.plugins.duel import duel_penalty  # noqa: F401 — 注册惩罚消息 matcher
from src.plugins.duel.config import plugin_config
from src.plugins.duel.duel_bots import is_bot_qq, pick_random_duel_bot_pair
from src.plugins.duel.duel_penalty import apply_duel_penalties
from src.plugins.duel.duel_qte import complete_duel_qte, duel_qte_exact_rule
from src.plugins.duel.duel_round_engine import (
    end_duel_group,
    play_duel_rounds,
    reload_event_pools,
    try_begin_duel_group,
)
from src.plugins.duel.duel_session import clear_duel_pair, start_duel_pair

__plugin_meta__ = PluginMetadata(
    name="牛牛决斗",
    description=("泰拉风味多幕擂台，与群友或牛牛对决"),
    usage="""
1. 发起对决
    · 发送「牛牛决斗」并 @ 一名群友或牛牛
    · 双牛：「牛牛决斗」@ 两只牛牛；或发送「八角笼牛」随机抽两只在线牛牛
2. 对战过程
    · 双方各有生命值
    · 部分幕面限时抢答：按提示发送干员全名或关键词；答对、答错、超时或乱入认错都会改血
    · 干员乱入时需辨认并喊出名字；认对可助战，认错会挨对方技能
    · 同一群同时只能进行一场决斗
3. 胜负
    · 全部幕数演完或一方血量归零即分胜负；
4. 维护
    · 「决斗事件重载」热更新剧情包与干员表
。
    """.strip(),
    type="application",
    homepage="https://github.com/PallasBot/Pallas-Bot",
    supported_adapters={"~onebot.v11"},
    extra={
        "version": "3.0.0",
        "menu_template": "default",
        "command_permissions": [
            {"id": "duel.duel", "label": "牛牛决斗", "default": "everyone"},
            {"id": "duel.cage", "label": "八角笼牛", "default": "everyone"},
            {
                "id": "duel.reload_events",
                "label": "决斗事件重载",
                "default": "group_moderator",
            },
        ],
        "menu_data": [
            {
                "func": "牛牛决斗",
                "trigger_method": "on_message",
                "trigger_condition": "牛牛决斗 @一名对手",
                "command_permission": "duel.duel",
                "brief_des": "泰拉风味多幕擂台，与群友或牛牛对决",
                "detail_des": ("挑战者 @ 一名决斗者即可开战，按终局血量判胜负，一方可先被 KO。"),
            },
            {
                "func": "双牛决斗",
                "trigger_method": "on_message",
                "trigger_condition": "牛牛决斗 @牛A @牛B",
                "command_permission": "duel.duel",
                "brief_des": "指定两只牛牛同台对决",
                "detail_des": ("两名被 @ 者须均为牛牛账号，规则与单人决斗相同。对战期间两头牛在本群互可见消息。"),
            },
            {
                "func": "八角笼牛",
                "trigger_method": "on_message",
                "trigger_condition": "八角笼牛",
                "command_permission": "duel.cage",
                "brief_des": "随机抽两只在线牛牛对决",
                "detail_des": "从本群当前在线的牛牛账号中随机配对开战，无需手动 @。",
            },
            {
                "func": "决斗抢答",
                "trigger_method": "on_message",
                "trigger_condition": "决斗进行中，按幕面提示发送干员名或关键词",
                "brief_des": "限时抢答影响血量",
                "detail_des": (
                    "幕面出现抢答时，在时限内发送正确干员全名或关键词可占优；"
                    "干员乱入须喊出正确名字，认错会挨技能。发错、超时同样失利。"
                    "牛牛参与时可能自动应答。"
                ),
            },
            {
                "func": "决斗事件重载",
                "trigger_method": "on_message",
                "trigger_condition": "决斗事件重载",
                "command_permission": "duel.reload_events",
                "brief_des": "热更新泰拉剧情包与干员名单",
                "detail_des": ("立即重载 default 剧情包与干员表，并取消进行中的抢答。"),
            },
        ],
    },
)

BLOCK_LIST: list[int] = []

DUEL_COOLDOWN_KEY = "duel"


async def is_reload_duel_events(bot: Bot, event: GroupMessageEvent, state: T_State) -> bool:
    if event.group_id in BLOCK_LIST:
        return False
    return event.get_plaintext().strip() == "决斗事件重载"


async def is_duel_msg(bot: Bot, event: GroupMessageEvent, state: T_State) -> bool:
    if event.group_id in BLOCK_LIST:
        return False
    return event.get_plaintext().strip().startswith("牛牛决斗")


async def is_cage_msg(bot: Bot, event: GroupMessageEvent, state: T_State) -> bool:
    if event.group_id in BLOCK_LIST:
        return False
    return event.get_plaintext().strip() == "八角笼牛"


duel_msg = on_message(
    priority=3,
    block=True,
    rule=Rule(is_duel_msg),
    permission=group_message_permission_for_command("duel.duel"),
)
cage_msg = on_message(
    priority=3,
    block=True,
    rule=Rule(is_cage_msg),
    permission=group_message_permission_for_command("duel.cage"),
)
duel_qte_msg = on_message(
    priority=2,
    block=True,
    rule=duel_qte_exact_rule,
    permission=permission.GROUP,
)
reload_duel_events_msg = on_message(
    priority=10,
    block=False,
    rule=Rule(is_reload_duel_events),
    permission=group_message_permission_for_command("duel.reload_events"),
)


def parse_at_qqs(event: GroupMessageEvent) -> list[str]:
    return [str(seg.data["qq"]) for seg in event.message if seg.type == "at" and seg.data.get("qq") is not None]


async def run_duel_match(
    matcher,
    event: GroupMessageEvent,
    challenger_id: str,
    defender_id: str,
    *,
    dual_bot: bool = False,
) -> None:
    """开团：仅多 Bot 抢命令冷却，无重复开团群 CD。"""
    challenger_is_bot = is_bot_qq(challenger_id)
    defender_is_bot = is_bot_qq(defender_id)
    bot_mode = dual_bot or (challenger_is_bot and defender_is_bot)

    if not try_begin_duel_group(event.group_id):
        await matcher.send("此群台上正有决斗未散，且待战歌落幕。")
        return

    bot_cfg = BotConfig(
        int(event.self_id),
        event.group_id,
        cooldown=plugin_config.duel_bot_cooldown_sec,
    )

    if not await bot_cfg.is_cooldown(DUEL_COOLDOWN_KEY):
        end_duel_group(event.group_id)
        return

    await bot_cfg.refresh_cooldown(DUEL_COOLDOWN_KEY)

    if bot_mode:
        await start_duel_pair(event.group_id, int(challenger_id), int(defender_id))

    try:
        stacks = await play_duel_rounds(
            matcher,
            event.group_id,
            challenger_id,
            defender_id,
            bot_mode=bot_mode,
            challenger_is_bot=challenger_is_bot,
            defender_is_bot=defender_is_bot,
        )
    finally:
        end_duel_group(event.group_id)
        if bot_mode:
            await clear_duel_pair(event.group_id)

    if stacks is None:
        await matcher.send("节庆剧目表读不出来……请检查插件内 event_packs/default 下 JSON。")
        return

    await apply_duel_penalties(
        event.group_id,
        int(event.self_id),
        challenger_id,
        defender_id,
        stacks,
        dual_bot=bot_mode,
    )


async def duel_bot_pair(matcher, bot: Bot, event: GroupMessageEvent, a: str, b: str) -> None:
    if a == b:
        await matcher.send("同一头牛不能左右互搏哦。")
        return
    await matcher.send(
        MessageSegment.text("战斗开始！")
        + MessageSegment.at(int(a))
        + MessageSegment.text(" 与 ")
        + MessageSegment.at(int(b))
        + MessageSegment.text(" 登台。")
    )
    await run_duel_match(matcher, event, a, b, dual_bot=True)


async def duel(matcher, bot: Bot, event: GroupMessageEvent, state: T_State) -> None:
    ats = parse_at_qqs(event)

    if len(ats) >= 2:
        if not (is_bot_qq(ats[0]) and is_bot_qq(ats[1])):
            await matcher.send("双 @ 决斗仅支持两名牛牛；人类请 @ 一名对手。")
            return
        await duel_bot_pair(matcher, bot, event, ats[0], ats[1])
        return

    if len(ats) == 0:
        await matcher.send(
            "台上还缺一位对手，无法开演。\n"
            "请发送「牛牛决斗」并 @ 一名决斗者（群友或牛牛均可）。\n"
            "双牛同台可 @ 两只牛牛，或发送「八角笼牛」随机抽选。"
        )
        return

    defender = ats[0]
    match = re.search(r"user_id=(\d+)", str(event.sender))
    if not match:
        await matcher.send("无法识别挑战者。")
        return
    challenger = match.group(1)

    if challenger == defender:
        await matcher.send("左脚踩右脚也不能上天哦。")
        return

    await run_duel_match(matcher, event, challenger, defender)


@duel_msg.handle()
async def _(bot: Bot, event: GroupMessageEvent, state: T_State) -> None:
    await duel(duel_msg, bot, event, state)


@cage_msg.handle()
async def _(bot: Bot, event: GroupMessageEvent, state: T_State) -> None:
    pair = await pick_random_duel_bot_pair(event.group_id)
    if not pair:
        await cage_msg.send("没有另一位对手呢，博士，八角笼无法开演……")
        return
    await duel_bot_pair(cage_msg, bot, event, str(pair[0]), str(pair[1]))


@duel_qte_msg.handle()
async def _(bot: Bot, event: GroupMessageEvent, state: T_State) -> None:
    if event.group_id in BLOCK_LIST:
        return
    complete_duel_qte(event)


@reload_duel_events_msg.handle()
async def _(bot: Bot, event: GroupMessageEvent, state: T_State) -> None:
    if event.group_id in BLOCK_LIST:
        return
    await reload_duel_events_msg.send(reload_event_pools())
