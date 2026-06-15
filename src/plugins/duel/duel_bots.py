"""群内在线牛牛探测与决斗入口解析。"""

from __future__ import annotations

import asyncio
import random
import re
from typing import TYPE_CHECKING, Any

from nonebot import get_bots, logger

from src.platform.multi_bot.dedup import normalize_message_time
from src.platform.multi_bot.group_online_cache import (
    GROUP_ONLINE_TTL_SEC,
    NS_FLEET,
    NS_LOCAL_CONNECTED,
    clear_group_online_cache,
    get_cached_group_bot_ids,
    resolve_local_connected_bots_in_group,
    store_cached_group_bot_ids,
)
from src.platform.shard import context as shard_ctx
from src.plugins.block import is_fleet_bot_qq

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import GroupMessageEvent

_AT_CQ_RE = re.compile(r"\[CQ:at,qq=(\d+)")
_ROUND_COUNT_RE = re.compile(r"(\d{1,2})\s*(?:幕|回合)")

# 复读 fanout / 决斗等高频路径：按群缓存在线 fleet 牛，避免 member API 异常时反复全舰队 probe
_GROUP_ONLINE_BOTS_TTL_SEC = GROUP_ONLINE_TTL_SEC


def clear_group_online_bot_ids_cache() -> None:
    clear_group_online_cache(NS_FLEET)
    clear_group_online_cache(NS_LOCAL_CONNECTED)


def normalize_onebot_api_payload(raw: Any) -> Any:
    if hasattr(raw, "model_dump"):
        return raw.model_dump()
    if hasattr(raw, "dict") and callable(raw.dict):
        return raw.dict()
    return raw


def user_id_from_member_row(row: Any) -> int | None:
    if isinstance(row, dict):
        uid = row.get("user_id") or row.get("uin") or row.get("qq")
    else:
        uid = getattr(row, "user_id", None) or getattr(row, "uin", None) or getattr(row, "qq", None)
    if uid is None:
        return None
    try:
        return int(uid)
    except (TypeError, ValueError):
        return None


def user_ids_from_member_rows(rows: Any) -> set[int]:
    if not isinstance(rows, list):
        return set()
    out: set[int] = set()
    for row in rows:
        uid = user_id_from_member_row(row)
        if uid is not None:
            out.add(uid)
    return out


def parse_group_member_list_user_ids(raw: Any) -> set[int]:
    """从 get_group_member_list / call_api 返回值解析成员 QQ。"""
    raw = normalize_onebot_api_payload(raw)
    if isinstance(raw, list):
        return user_ids_from_member_rows(raw)
    if not isinstance(raw, dict):
        return set()
    for key in ("member_list", "members", "list", "data"):
        val = raw.get(key)
        if isinstance(val, list):
            ids = user_ids_from_member_rows(val)
            if ids:
                return ids
        if isinstance(val, dict):
            nested = parse_group_member_list_user_ids(val)
            if nested:
                return nested
    for val in raw.values():
        if isinstance(val, list):
            ids = user_ids_from_member_rows(val)
            if ids:
                return ids
    return set()


async def probe_fleet_bots_in_group(caller: Any, group_id: int, catalog: frozenset[int]) -> list[int]:
    """并发 get_group_member_info 确认本群内的 fleet 牛。"""
    sem = asyncio.Semaphore(8)

    async def one(bid: int) -> int | None:
        async with sem:
            try:
                await caller.get_group_member_info(  # type: ignore[union-attr]
                    group_id=group_id,
                    user_id=int(bid),
                    no_cache=True,
                )
            except Exception:
                return None
            return int(bid)

    results = await asyncio.gather(*(one(int(b)) for b in sorted(catalog)))
    return sorted(x for x in results if x is not None)


async def list_group_online_bot_ids(group_id: int) -> list[int]:
    """已连接且能查到本群资料的牛牛 QQ；分片时含其它 worker 上在线的 fleet 牛。"""
    gid = int(group_id)
    cached = get_cached_group_bot_ids(gid, namespace=NS_FLEET)
    if cached is not None:
        return cached

    result = await resolve_shard_group_online_bot_ids(gid)
    await store_cached_group_bot_ids(gid, result, namespace=NS_FLEET)
    return result


async def resolve_unified_group_online_bot_ids(group_id: int) -> list[int]:
    """单进程多账号：本进程已连接 fleet 牛 ∩ 本群成员。"""
    from src.platform.multi_bot.fleet import get_catalog_bot_ids

    catalog = get_catalog_bot_ids()
    if not catalog:
        return []
    bots = get_bots()
    caller = None
    for key in sorted(bots.keys(), key=lambda x: int(x) if str(x).isdigit() else 0):
        try:
            bid = int(key)
        except ValueError:
            continue
        if bid in catalog:
            caller = bots[key]
            break
    if caller is None:
        return []
    local = frozenset(int(k) for k in bots if str(k).isdigit()) & catalog
    member_ids: set[int] = set()
    try:
        raw = await caller.get_group_member_list(group_id=group_id, no_cache=True)  # type: ignore[union-attr]
        member_ids = parse_group_member_list_user_ids(raw)
        out = sorted(q for q in local if q in member_ids)
        if len(out) >= 2:
            return out
    except Exception:
        pass
    probed = await probe_fleet_bots_in_group(caller, group_id, local)
    if len(probed) >= 2:
        return probed
    return await resolve_local_connected_bots_in_group(group_id)


async def resolve_shard_group_online_bot_ids(group_id: int) -> list[int]:
    """分片：解析本群可用 fleet 牛。"""
    from src.platform.multi_bot.fleet import get_catalog_bot_ids
    from src.platform.shard.presence import get_cluster_online_bot_ids, pick_local_query_bot

    if not shard_ctx.sharding_active():
        return await resolve_unified_group_online_bot_ids(group_id)

    caller = pick_local_query_bot()
    if caller is None:
        return []

    catalog = get_catalog_bot_ids()
    out: list[int] = []
    member_ids: set[int] = set()
    list_err: str | None = None
    list_empty = False
    member_api_unusable = False
    raw: Any = None
    try:
        raw = await caller.get_group_member_list(group_id=group_id, no_cache=True)  # type: ignore[union-attr]
        member_ids = parse_group_member_list_user_ids(raw)
        if isinstance(raw, list) and len(raw) == 0:
            list_empty = True
            member_api_unusable = True
        elif not member_ids:
            member_api_unusable = True
        else:
            out = sorted(q for q in catalog if q in member_ids)
    except Exception as err:
        list_err = str(err)
        list_empty = True
        member_api_unusable = True

    if len(out) >= 2:
        return out

    relaxed = sorted(q for q in catalog if q in get_cluster_online_bot_ids())
    # member list 不可用且 presence 足够：跳过全 catalog 逐号 probe
    if member_api_unusable and len(relaxed) >= 2:
        logger.warning(
            "duel: group {} member API unusable, use presence-online fleet (n={})",
            group_id,
            len(relaxed),
        )
        return relaxed

    probed = await probe_fleet_bots_in_group(caller, group_id, catalog)
    if len(probed) >= 2:
        if list_err:
            logger.warning(
                "duel: get_group_member_list failed group={} per-bot probe (found={}): {}",
                group_id,
                len(probed),
                list_err,
            )
        elif list_empty or not member_ids:
            logger.warning(
                "duel: member list empty/unparsed group={} per-bot probe (found={})",
                group_id,
                len(probed),
            )
        else:
            logger.warning(
                "duel: group {} fleet∩member_list={} catalog={} per-bot probe (found={})",
                group_id,
                len(out),
                len(catalog),
                len(probed),
            )
        return probed

    if len(relaxed) >= 2:
        logger.warning(
            "duel: group {} member API unusable, use presence-online fleet (n={})",
            group_id,
            len(relaxed),
        )
        return relaxed

    if list_err:
        logger.warning(
            "duel: get_group_member_list failed group={} fallback per-bot probe (found={}): {}",
            group_id,
            len(probed),
            list_err,
        )
    elif list_empty or not member_ids:
        sample = repr(raw)
        if len(sample) > 400:
            sample = sample[:400] + "..."
        logger.warning(
            "duel: member list empty/unparsed group={} type={} sample={} probe_found={}",
            group_id,
            type(raw).__name__,
            sample,
            len(probed),
        )
    elif probed:
        logger.warning(
            "duel: group {} fleet∩member_list={} catalog={} per-bot probe (found={})",
            group_id,
            len(out),
            len(catalog),
            len(probed),
        )

    out = probed
    if len(out) < 2:
        logger.warning(
            "duel: group {} has {} fleet bot(s) after probe (catalog={}, presence={})",
            group_id,
            len(out),
            len(catalog),
            len(relaxed),
        )
    return out


async def fleet_bot_confirmed_in_group(bot: Any, group_id: int) -> bool:
    """当前牛牛账号是否在该群。"""
    try:
        bid = int(bot.self_id)
    except (AttributeError, TypeError, ValueError):
        return False
    if not is_fleet_bot_qq(bid):
        return False
    try:
        await bot.get_group_member_info(group_id=group_id, user_id=bid, no_cache=True)
        return True
    except Exception:
        return False


async def list_local_fleet_bots_in_group(group_id: int) -> list[int]:
    """本 worker 已连接且能确认在本群的 fleet 牛。"""
    from src.platform.multi_bot.fleet import get_catalog_bot_ids
    from src.platform.shard.presence import pick_local_query_bot

    caller = pick_local_query_bot()
    if caller is None:
        return []
    local = frozenset(int(k) for k in get_bots() if str(k).isdigit())
    scope = local & frozenset(get_catalog_bot_ids())
    if not scope:
        return []
    try:
        raw = await caller.get_group_member_list(group_id=group_id, no_cache=True)  # type: ignore[union-attr]
        member_ids = parse_group_member_list_user_ids(raw)
        if member_ids:
            return sorted(q for q in scope if q in member_ids)
    except Exception:
        pass
    probed = await probe_fleet_bots_in_group(caller, group_id, scope)
    if probed:
        return probed
    out: list[int] = []
    for bid in sorted(scope):
        try:
            await caller.get_group_member_info(group_id=group_id, user_id=int(bid), no_cache=True)  # type: ignore[union-attr]
        except Exception:
            continue
        out.append(int(bid))
    return out


async def pick_random_duel_bot_pair(group_id: int) -> tuple[int, int] | None:
    """随机两只在线牛。"""
    ids = await list_group_online_bot_ids(group_id)
    if len(ids) < 2:
        return None
    a, b = random.sample(ids, 2)
    return a, b


def cage_pair_seed(group_id: int, user_id: int, message_time: int) -> int:
    """同群同一条八角笼指令，各 Bot 算出相同配对。"""
    t = normalize_message_time(message_time)
    return group_id * 1_000_000_007 + user_id * 1_000_003 + t


async def pick_cage_duel_bot_pair(
    group_id: int,
    user_id: int,
    message_time: int,
    *,
    plaintext: str = "八角笼牛",
) -> tuple[int, int] | None:
    """八角笼：从本群在线牛中按群+发送者+时间种子固定配对。"""
    ids = sorted(await list_group_online_bot_ids(group_id))
    if len(ids) < 2:
        return None
    a, b = random.Random(cage_pair_seed(group_id, user_id, message_time)).sample(ids, 2)
    return a, b


def is_pallas_bot(qq: int | str) -> bool:
    return is_fleet_bot_qq(int(qq))


def is_bot_qq(qq: str) -> bool:
    try:
        return is_fleet_bot_qq(int(qq))
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
    if raw and ("[CQ:at," in raw or "at,qq=" in raw):
        for m in _AT_CQ_RE.finditer(raw):
            s = m.group(1)
            if s != "all" and s not in seen:
                seen.add(s)
                qqs.append(s)
    return qqs


def raw_message_has_at(event: GroupMessageEvent) -> bool:
    """raw 中是否含 @。"""
    raw = getattr(event, "raw_message", None) or ""
    if "[CQ:at," not in raw and "at,qq=" not in raw:
        return False
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
