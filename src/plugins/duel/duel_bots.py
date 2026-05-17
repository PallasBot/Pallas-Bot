"""群内在线牛牛探测与决斗入口解析。"""

from __future__ import annotations

import random
import re
from typing import TYPE_CHECKING

from nonebot import get_bots

from src.plugins.block import plugin_config

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import GroupMessageEvent

_AT_CQ_RE = re.compile(r"\[CQ:at,qq=(\d+)")
_ROUND_COUNT_RE = re.compile(r"(\d{1,2})\s*(?:幕|回合)")
_CAGE_CMD_RE = re.compile(r"^八角笼(?:牛|斗)(?:\s*(\d{1,2}\s*(?:幕|回合)))?\s*$")


async def list_group_online_bot_ids(group_id: int) -> list[int]:
    """当前进程已连接、且能查到本群资料的牛牛 QQ。"""
    bots = get_bots()
    out: list[int] = []
    for bid in sorted(plugin_config.bots):
        key = str(bid)
        if key not in bots:
            continue
        try:
            await bots[key].get_group_member_info(group_id=group_id, user_id=int(bid), no_cache=True)
        except Exception:
            continue
        out.append(int(bid))
    return out


async def pick_random_duel_bot_pair(group_id: int) -> tuple[int, int] | None:
    """随机两只在线牛（非八角笼；各 Bot 实例勿共用）。"""
    ids = await list_group_online_bot_ids(group_id)
    if len(ids) < 2:
        return None
    a, b = random.sample(ids, 2)
    return a, b


def cage_pair_seed(group_id: int, user_id: int, message_time: int) -> int:
    """同群同一条八角笼指令，各 Bot 算出相同配对（不依赖各端 message_id）。"""
    return group_id * 1_000_000_007 + user_id * 1_000_003 + int(message_time)


async def pick_cage_duel_bot_pair(group_id: int, user_id: int, message_time: int) -> tuple[int, int] | None:
    """八角笼：从本群在线牛中按群+发送者+时间种子固定配对。"""
    ids = await list_group_online_bot_ids(group_id)
    if len(ids) < 2:
        return None
    a, b = random.Random(cage_pair_seed(group_id, user_id, message_time)).sample(ids, 2)
    return a, b


def is_pallas_bot(qq: int | str) -> bool:
    return int(qq) in plugin_config.bots


def is_bot_qq(qq: str) -> bool:
    try:
        return int(qq) in plugin_config.bots
    except ValueError:
        return False


def duel_narrator_bot_id(challenger_id: str, defender_id: str, *, dual_bot: bool) -> int | None:
    """应由哪只牛主持发幕；人 vs 人 返回 None，由消息抢占决定。"""
    if dual_bot:
        return min(int(challenger_id), int(defender_id))
    if is_bot_qq(defender_id):
        return int(defender_id)
    if is_bot_qq(challenger_id):
        return int(challenger_id)
    return None


def is_cage_plaintext(text: str) -> bool:
    """八角笼牛/八角笼斗，可选末尾 N幕/N回合。"""
    return bool(_CAGE_CMD_RE.match(text.strip()))


def parse_duel_round_count_from_text(text: str) -> int | None:
    """从纯文本解析「N幕」「N回合」；未写则 None。"""
    m = _ROUND_COUNT_RE.search(text.strip())
    if not m:
        return None
    return int(m.group(1))


def resolve_duel_round_count(event: GroupMessageEvent) -> tuple[int, str | None]:
    """(本局幕数, 错误提示)；未指定幕数时用配置默认。"""
    from src.plugins.duel.config import plugin_config

    specified = parse_duel_round_count_from_text(event.get_plaintext())
    if specified is None:
        return plugin_config.duel_total_rounds, None
    lo = 1
    hi = plugin_config.duel_player_rounds_max
    if specified < lo or specified > hi:
        return plugin_config.duel_total_rounds, f"博士，我只能组织{lo}～{hi} 幕的决斗"
    return specified, None


def parse_duel_at_qqs(event: GroupMessageEvent) -> list[str]:
    """解析 @ 列表；合并 message 段与 raw CQ，去重保序。"""
    qqs: list[str] = []
    seen: set[str] = set()
    for seg in event.message:
        if seg.type != "at":
            continue
        qq = seg.data.get("qq")
        if qq is None:
            continue
        s = str(qq)
        if s == "all" or s in seen:
            continue
        seen.add(s)
        qqs.append(s)
    raw = getattr(event, "raw_message", None) or ""
    if raw:
        for m in _AT_CQ_RE.finditer(raw):
            s = m.group(1)
            if s != "all" and s not in seen:
                seen.add(s)
                qqs.append(s)
    return qqs


def raw_message_has_at(event: GroupMessageEvent) -> bool:
    """raw 中是否含 @（本牛看不到 message.at 时用于避免误报缺对手）。"""
    raw = getattr(event, "raw_message", None) or ""
    return bool(_AT_CQ_RE.search(raw))


def infer_duel_defender_when_at_self_hidden(event: GroupMessageEvent) -> str | None:
    """被 @ 的本牛有时收不到 at 段；raw 里仍有 CQ 时补全为防守方。"""
    self_id = str(event.self_id)
    if not is_bot_qq(self_id):
        return None
    raw = getattr(event, "raw_message", None) or ""
    if f"[CQ:at,qq={self_id}" in raw or f"at,qq={self_id}" in raw:
        return self_id
    return None
