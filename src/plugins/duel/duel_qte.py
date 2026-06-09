from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from nonebot import logger
from nonebot.adapters import Bot, Event  # noqa: TC002
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message
from nonebot.matcher import Matcher  # noqa: TC002
from nonebot.rule import Rule

from src.plugins.block import is_fleet_bot_qq
from src.plugins.duel.config import plugin_config
from src.plugins.duel.duel_message import (
    append_duel_message,
    duel_at,
    duel_join_lines,
    duel_plain,
    duel_text,
    message_has_content,
)
from src.plugins.duel.duel_terms import (
    EXCHANGE_QTE_DEFAULT_PROMPT,
    EXCHANGE_QTE_RACE_PROMPT,
    QTE_FAIL_TAIL,
    QTE_INTRUSION_FAIL_STUB,
    QTE_INTRUSION_RACE_DRAW_TAIL,
    QTE_INTRUSION_RACE_TITLE,
    QTE_INTRUSION_RACE_WIN_TAIL,
    QTE_INTRUSION_TITLE,
    QTE_KEYWORD_TITLE,
    QTE_RACE_DRAW_TAIL,
    QTE_RACE_TITLE,
    QTE_RACE_WIN_TAIL,
    QTE_SUCCESS_TAIL,
)

if TYPE_CHECKING:
    from src.plugins.duel.duel_round_engine import LoadedEvent


@dataclass
class _DuelQteSession:
    future: asyncio.Future[bool]
    required_key: str
    deadline: float


_sessions: dict[tuple[str, str], _DuelQteSession] = {}


@dataclass
class _DuelRaceQteSession:
    future: asyncio.Future[str | None]
    required_key: str
    deadline: float
    challenger_id: str
    defender_id: str


_race_sessions: dict[str, _DuelRaceQteSession] = {}
_active_qte_groups: set[str] = set()
_active_qte_users_by_group: dict[str, frozenset[str]] = {}
_cluster_qte_users: dict[str, frozenset[str]] = {}
_cluster_qte_deadline: dict[str, float] = {}
_published_greeting_snapshot: dict[str, frozenset[str]] = {}


def apply_cluster_qte_greeting(gid: str, users: frozenset[str] | None, deadline: float) -> None:
    """各 worker 通过 Redis pub/sub 同步的 QTE 参与者（供 greeting 让路）。"""
    if users:
        _cluster_qte_users[gid] = users
        _cluster_qte_deadline[gid] = deadline
        return
    _cluster_qte_users.pop(gid, None)
    _cluster_qte_deadline.pop(gid, None)


def publish_cluster_qte_greeting_if_changed(gid: str, users: frozenset[str], deadline: float) -> None:
    from src.platform.shard.registry.config import is_sharding_active

    if not is_sharding_active():
        return
    snapshot = users or frozenset()
    if _published_greeting_snapshot.get(gid) == snapshot:
        return
    if snapshot:
        _published_greeting_snapshot[gid] = snapshot
    else:
        _published_greeting_snapshot.pop(gid, None)
    from src.platform.shard.coord.duel_qte_redis import (
        clear_duel_qte_greeting_redis_sync,
        publish_duel_qte_greeting_redis_sync,
    )

    if snapshot:
        publish_duel_qte_greeting_redis_sync(gid, snapshot, deadline=deadline)
    else:
        clear_duel_qte_greeting_redis_sync(gid)


def sync_active_qte_group(gid: str) -> None:
    """会话增减后刷新群级活跃标记（供 greeting 热路径快速查询）。"""
    now = time.time()
    active_users: set[str] = set()
    max_deadline = now
    race = _race_sessions.get(gid)
    if race is not None and not race.future.done() and now <= race.deadline:
        active_users.update((str(race.challenger_id), str(race.defender_id)))
        max_deadline = max(max_deadline, race.deadline)
    for (g, uid), sess in _sessions.items():
        if g == gid and not sess.future.done() and now <= sess.deadline:
            active_users.add(str(uid))
            max_deadline = max(max_deadline, sess.deadline)
    if active_users:
        user_frozen = frozenset(active_users)
        _active_qte_groups.add(gid)
        _active_qte_users_by_group[gid] = user_frozen
        publish_cluster_qte_greeting_if_changed(gid, user_frozen, max_deadline)
        return
    _active_qte_groups.discard(gid)
    _active_qte_users_by_group.pop(gid, None)
    publish_cluster_qte_greeting_if_changed(gid, frozenset(), now)


def duel_qte_active_in_group(group_id: int) -> bool:
    """本群是否存在未过期且未完成的 QTE 会话（供 greeting 等让路）。"""
    gid = str(group_id)
    if gid not in _active_qte_groups:
        return False
    sync_active_qte_group(gid)
    return gid in _active_qte_groups


def duel_qte_blocks_greeting_user(group_id: int, user_id: str | int) -> bool:
    """仅当该用户正参与本群 QTE 时，屏蔽 greeting 抢占。"""
    gid = str(group_id)
    uid = str(user_id)
    if gid in _active_qte_groups:
        sync_active_qte_group(gid)
        users = _active_qte_users_by_group.get(gid)
        if users and uid in users:
            return True
    cluster_users = _cluster_qte_users.get(gid)
    if cluster_users and uid in cluster_users:
        if time.time() <= _cluster_qte_deadline.get(gid, 0):
            return True
        _cluster_qte_users.pop(gid, None)
        _cluster_qte_deadline.pop(gid, None)
    from src.platform.shard.registry.config import is_sharding_active

    if is_sharding_active():
        from src.platform.shard.coord.duel_qte_redis import greeting_user_blocked_redis_sync

        if greeting_user_blocked_redis_sync(gid, uid):
            return True
    return False


def qte_session_id(group_id: int, user_id: str | int) -> tuple[str, str]:
    return str(group_id), str(user_id)


_KEYWORD_DECOY = ["格挡", "盾反", "架开", "闪避", "硬扛", "换血", "撤退", "咏唱打断", "不对"]


def bot_qte_success_rate(qte_kind: str) -> float:
    if qte_kind == "intrusion":
        return plugin_config.duel_bot_qte_intrusion_success_rate
    return plugin_config.duel_bot_qte_keyword_success_rate


def pick_wrong_intrusion_name(correct: str) -> str:
    from src.plugins.duel.arknights_ops import get_operators_payload

    ops = get_operators_payload().get("operators")
    pool: list[str] = []
    if isinstance(ops, list):
        pool = [
            str(o.get("name", "")).strip()
            for o in ops
            if isinstance(o, dict) and str(o.get("name", "")).strip() and o.get("name") != correct
        ]
    if pool:
        return random.choice(pool)
    if len(correct) > 1:
        return correct[:-1]
    return "未命名干员"


def pick_wrong_keyword_reply(correct: str, decoy_keys: list[str] | None) -> str:
    base = decoy_keys or _KEYWORD_DECOY
    pool = [str(k) for k in base if str(k) != correct]
    return random.choice(pool) if pool else "……"


def pick_bot_wrong_qte_reply(correct: str, qte_kind: str, *, decoy_keys: list[str] | None = None) -> str | None:
    """失败时可能嘴瓢或沉默。"""
    if random.random() < plugin_config.duel_bot_qte_fail_silent_chance:
        return None
    if random.random() >= plugin_config.duel_bot_qte_fail_speak_wrong_chance:
        return None
    if qte_kind == "intrusion":
        return pick_wrong_intrusion_name(correct)
    return pick_wrong_keyword_reply(correct, decoy_keys)


def should_schedule_bot_qte_auto_answer(responder: str) -> bool:
    """fleet 牛牛且 WS 连在本进程时才在本进程调度自动 QTE。"""
    try:
        qq = int(responder)
    except (TypeError, ValueError):
        return False
    if not is_fleet_bot_qq(qq):
        return False
    from src.platform.shard.presence import bot_has_local_connection

    return bot_has_local_connection(qq)


def should_delegate_bot_qte_to_coord(responder: str) -> bool:
    """分片且应答牛在其它 worker：走 Redis 共享 QTE 会话。"""
    from src.platform.shard.registry.config import is_sharding_active

    if not is_sharding_active():
        return False
    try:
        qq = int(responder)
    except (TypeError, ValueError):
        return False
    if not is_fleet_bot_qq(qq):
        return False
    from src.platform.shard.presence import bot_has_local_connection

    return not bot_has_local_connection(qq)


def race_qte_needs_coord(challenger_id: str, defender_id: str) -> bool:
    from src.platform.shard.registry.config import is_sharding_active

    if not is_sharding_active():
        return False
    return should_delegate_bot_qte_to_coord(challenger_id) or should_delegate_bot_qte_to_coord(defender_id)


def bot_race_qte_use_cluster_coord(challenger_id: str, defender_id: str) -> bool:
    """分片下含 fleet 牛的抢答 QTE 统一走 coord，避免主持 worker 本地抢跑。"""
    from src.platform.shard.registry.config import is_sharding_active

    if not is_sharding_active():
        return False

    def fleet(uid: str) -> bool:
        try:
            return is_fleet_bot_qq(int(uid))
        except (TypeError, ValueError):
            return False

    return fleet(challenger_id) or fleet(defender_id)


def schedule_bot_qte_auto_answer(
    group_id: int,
    responder: str,
    required_key: str,
    fut: asyncio.Future[bool],
    window_sec: int,
    *,
    qte_kind: str = "keyword",
    decoy_keys: list[str] | None = None,
) -> None:
    """应答方为牛时自动咏名/拆招，按概率成功或嘴瓢失败。"""
    if should_delegate_bot_qte_to_coord(responder):
        from src.platform.shard.coord.duel_qte import schedule_cross_shard_single_qte

        schedule_cross_shard_single_qte(
            group_id,
            responder,
            required_key,
            fut,
            window_sec,
            qte_kind=qte_kind,
            decoy_keys=decoy_keys,
        )
        return
    if not should_schedule_bot_qte_auto_answer(responder):
        return

    async def job() -> None:
        from nonebot import get_bots

        delay = random.uniform(1.2, min(6.0, max(2.0, window_sec - 0.8)))
        success_roll = random.random() < bot_qte_success_rate(qte_kind)
        if not success_roll:
            delay += random.uniform(0.4, 1.8)
        await asyncio.sleep(delay)
        if fut.done():
            return
        outgoing = (
            required_key if success_roll else pick_bot_wrong_qte_reply(required_key, qte_kind, decoy_keys=decoy_keys)
        )
        if outgoing:
            try:
                inst = get_bots().get(str(responder))
                if inst is not None:
                    await inst.send_group_msg(group_id=group_id, message=outgoing)
            except Exception as err:
                logger.debug(f"duel bot qte send failed: {err}")
        if not fut.done():
            fut.set_result(bool(success_roll and outgoing == required_key))
            sync_active_qte_group(str(group_id))

    asyncio.create_task(job())


def schedule_bot_race_qte_auto_answer(
    group_id: int,
    challenger_id: str,
    defender_id: str,
    required_key: str,
    fut: asyncio.Future[str | None],
    window_sec: int,
    *,
    qte_kind: str = "keyword",
    decoy_keys: list[str] | None = None,
) -> None:
    """双方均为牛时各自自动抢答，先成功者写入 future。"""
    if bot_race_qte_use_cluster_coord(challenger_id, defender_id):
        from src.platform.shard.coord.duel_qte import (
            bridge_race_qte_coord,
            schedule_cross_shard_race_qte,
        )

        coord_sid = schedule_cross_shard_race_qte(
            group_id,
            challenger_id,
            defender_id,
            required_key,
            fut,
            window_sec,
            qte_kind=qte_kind,
            decoy_keys=decoy_keys,
        )
        asyncio.create_task(bridge_race_qte_coord(coord_sid, fut, window_sec=window_sec))
        return

    coord_sid: str | None = None
    if race_qte_needs_coord(challenger_id, defender_id):
        from src.platform.shard.coord.duel_qte import (
            bridge_race_qte_coord,
            schedule_cross_shard_race_qte,
        )

        coord_sid = schedule_cross_shard_race_qte(
            group_id,
            challenger_id,
            defender_id,
            required_key,
            fut,
            window_sec,
            qte_kind=qte_kind,
            decoy_keys=decoy_keys,
        )
        asyncio.create_task(bridge_race_qte_coord(coord_sid, fut, window_sec=window_sec))

    for responder in (challenger_id, defender_id):
        if should_delegate_bot_qte_to_coord(responder):
            continue
        if not should_schedule_bot_qte_auto_answer(responder):
            continue

        async def job(responder_id: str = responder, race_coord_sid: str | None = coord_sid) -> None:
            from nonebot import get_bots

            delay = random.uniform(1.0, min(5.5, max(1.8, window_sec - 1.0)))
            success_roll = random.random() < bot_qte_success_rate(qte_kind)
            if not success_roll:
                delay += random.uniform(0.3, 1.5)
            await asyncio.sleep(delay)
            if fut.done():
                return
            outgoing = (
                required_key
                if success_roll
                else pick_bot_wrong_qte_reply(required_key, qte_kind, decoy_keys=decoy_keys)
            )
            if outgoing:
                try:
                    inst = get_bots().get(str(responder_id))
                    if inst is not None:
                        await inst.send_group_msg(group_id=group_id, message=outgoing)
                except Exception as err:
                    logger.debug(f"duel bot race qte send failed: {err}")
            if not success_roll or outgoing != required_key:
                return
            if race_coord_sid:
                from src.platform.shard.coord.duel_qte import try_claim_race_coord_winner

                await try_claim_race_coord_winner(race_coord_sid, responder_id)
            elif not fut.done():
                fut.set_result(responder_id)
                sync_active_qte_group(str(group_id))

        asyncio.create_task(job())


def qte_opponent_actor(actor: str) -> str:
    return "defender" if actor == "challenger" else "challenger"


def effect_harms_actor(eff: dict[str, Any], victim: str, actor: str) -> bool:
    etype = eff.get("type")
    if etype not in ("deal_damage", "add_self_debuff"):
        return False
    tgt = str(eff.get("target", "actor"))
    if tgt in ("actor", "self"):
        return victim == actor
    if tgt == "other":
        return victim == qte_opponent_actor(actor)
    return tgt == victim


def qte_success_attacks_opponent(effects: list[Any], actor: str) -> bool:
    """成功效果是否对 actor 的对手造成伤害。"""
    opponent = qte_opponent_actor(actor)
    for raw in effects:
        if isinstance(raw, dict) and effect_harms_actor(raw, opponent, actor):
            if raw.get("type") == "deal_damage":
                return True
    return False


_EXCHANGE_RACE_KEYS = ["突刺", "斩落", "贯索", "夺命"]
_EXCHANGE_DEFENSE_KEYS = ["格挡", "盾反", "架开", "闪避"]


def build_exchange_auto_qte(qte_actor: str) -> dict[str, Any]:
    """兵刃幕无内置 QTE 时，按配置生成守方拆招或双方抢攻。"""
    from src.plugins.duel.config import plugin_config

    if random.random() < plugin_config.duel_exchange_qte_race_chance:
        return {
            "mode": "race",
            "keys": list(_EXCHANGE_RACE_KEYS),
            "window_sec": 10,
            "prompt": EXCHANGE_QTE_RACE_PROMPT,
            "on_success_effects": [{"type": "deal_damage", "target": "other", "value": 2}],
            "on_fail_effects": [],
        }
    return {
        "target": qte_actor,
        "keys": list(_EXCHANGE_DEFENSE_KEYS),
        "window_sec": 10,
        "prompt": EXCHANGE_QTE_DEFAULT_PROMPT,
        "on_success_effects": [{"type": "add_dp", "target": qte_actor, "value": 1}],
        "on_fail_effects": [{"type": "deal_damage", "target": qte_actor, "value": 2}],
    }


def intrusion_should_race(spec: dict[str, Any]) -> bool:
    mode = str(spec.get("mode", "")).strip().lower()
    if mode == "race":
        return True
    if mode in ("single", "defend"):
        return False
    from src.plugins.duel.config import plugin_config

    return random.random() < plugin_config.duel_intrusion_race_chance


def qte_should_race(spec: dict[str, Any], actor: str) -> bool:
    mode = str(spec.get("mode", "")).strip().lower()
    if mode == "race":
        return True
    if mode in ("single", "defense", "defend"):
        return False
    on_ok = spec.get("on_success_effects", [])
    if not isinstance(on_ok, list):
        return False
    return qte_success_attacks_opponent(on_ok, actor)


def race_qte_damage_hint(effects: list[Any]) -> str:
    for raw in effects:
        if not isinstance(raw, dict) or raw.get("type") != "deal_damage":
            continue
        val = raw.get("value")
        if isinstance(val, int) and val > 0:
            return f"先声夺人者可再对对手造成{val}点伤害"
        if raw.get("use_damage"):
            return "先声夺人者可再痛击对手"
    return "先声夺人者可再补一刀"


def actor_from_user_id(user_id: str, challenger_id: str, defender_id: str) -> str:
    return "challenger" if str(user_id) == str(challenger_id) else "defender"


async def duel_qte_message_rule(bot: Bot, event: Event) -> bool:
    """仅当存在未过期且未完成的 QTE 会话、且文本与要求完全一致时放行。"""
    if not isinstance(event, GroupMessageEvent):
        return False
    plain = event.get_plaintext().strip()
    gid = str(event.group_id)
    race = _race_sessions.get(gid)
    if race is not None and not race.future.done() and time.time() <= race.deadline:
        uid = event.get_user_id()
        if uid in (race.challenger_id, race.defender_id):
            return plain == race.required_key
    sid = qte_session_id(event.group_id, event.get_user_id())
    sess = _sessions.get(sid)
    if sess is None or sess.future.done():
        return False
    if time.time() > sess.deadline:
        return False
    return plain == sess.required_key


duel_qte_exact_rule = Rule(duel_qte_message_rule)


def complete_duel_qte(event: GroupMessageEvent) -> None:
    """将当前群的 QTE 标记为成功（单人应答或抢攻争先）。"""
    gid = str(event.group_id)
    uid = event.get_user_id()
    race = _race_sessions.get(gid)
    if race is not None and not race.future.done() and uid in (race.challenger_id, race.defender_id):
        if event.get_plaintext().strip() == race.required_key:
            race.future.set_result(uid)
            sync_active_qte_group(gid)
        return
    sid = qte_session_id(event.group_id, uid)
    sess = _sessions.get(sid)
    if sess is None or sess.future.done():
        return
    sess.future.set_result(True)
    sync_active_qte_group(gid)


def resolve_qte_responder_qq(target: str, actor: str, challenger_id: str, defender_id: str) -> str:
    """把 qte.target 文案解析为实际应答 QQ。"""
    if target in ("actor", "self"):
        return challenger_id if actor == "challenger" else defender_id
    if target == "challenger":
        return challenger_id
    if target == "defender":
        return defender_id
    if target == "other":
        return defender_id if actor == "challenger" else challenger_id
    logger.warning(f"duel qte unknown target={target!r}, fallback actor")
    return challenger_id if actor == "challenger" else defender_id


def select_operator_intrusion_success_effects(spec: dict[str, Any], kind: str) -> list[Any]:
    """按 picked_skill_kind 选 on_success_effects_*，缺省依次回退其它表。"""
    key_map = {
        "heal": "on_success_effects_heal",
        "attack": "on_success_effects_attack",
        "neutral": "on_success_effects_neutral",
    }
    kind_key = kind if kind in key_map else "neutral"
    order = (
        key_map[kind_key],
        "on_success_effects_neutral",
        "on_success_effects_attack",
        "on_success_effects_heal",
        "on_success_effects",
    )
    for k in order:
        lst = spec.get(k)
        if isinstance(lst, list) and lst:
            return lst
    return []


def prepare_intrusion_fail_skill_effects(
    effects: list[Any],
    skill_kind: str,
) -> list[dict[str, Any]]:
    """唤名失败仍施放本幕已抽技能；治疗向的 hp/dp 改落在决斗另一方（相对本幕 actor）。"""
    rows = [dict(e) for e in effects if isinstance(e, dict)]
    if skill_kind != "heal":
        return rows
    out: list[dict[str, Any]] = []
    heal_redirected = False
    for eff in rows:
        etype = eff.get("type")
        tgt = str(eff.get("target", "actor"))
        if etype in ("heal_hp", "add_dp"):
            if etype == "heal_hp" and heal_redirected:
                continue
            eff = {**eff, "target": "other"}
            if etype == "heal_hp":
                heal_redirected = True
        elif etype in ("add_self_buff", "add_self_debuff") and tgt in (
            "actor",
            "self",
            "challenger",
            "defender",
            "both",
        ):
            eff = {**eff, "target": "other"}
        out.append(eff)
    return out


def default_intrusion_fail_post(skill_kind: str, actor: str, *, is_pallas: bool) -> str:
    """认错结算：攻击类打认错方；治疗类本意惩罚却落在另一方。"""
    punish = "<A>" if actor == "challenger" else "<B>"
    healed = "<B>" if actor == "challenger" else "<A>"
    if skill_kind == "heal":
        return f"<O> 似乎极为恼火——本想拿认错的人出气，却把「<SK>」施在了 {healed} 身上：\n<SKD>\n甩袖离去。"
    if is_pallas:
        return f"<O> 似乎极为不满，对 {punish} 释放「<SK>」：\n<SKD>\n冷冷离去。"
    return f"<O> 似乎极为恼火，对 {punish} 释放「<SK>」：\n<SKD>\n头也不回地走了。"


def default_intrusion_race_fail_post(skill_kind: str, *, is_pallas: bool) -> str:
    """抢认超时：双方皆未能咏名时的默认收场文案。"""
    if skill_kind == "heal":
        if is_pallas:
            return "<O> 久候无人咏名，漠然落下「<SK>」：\n<SKD>\n<A>与<B> 都没认对她，她已冷冷离去。"
        return "<O> 等了片刻仍无人认得——索性施放「<SK>」：\n<SKD>\n<A>与<B> 面面相觑，她转身走了。"
    if is_pallas:
        return "<O> 冷眼扫过——<A>与<B> 竟无人认得她，对二人释出「<SK>」：\n<SKD>\n冷冷离去。"
    return "<O> 似乎极为恼火——<A>与<B> 都没认出她是谁，当场对二人释放「<SK>」：\n<SKD>\n头也不回地走了。"


def resolve_intrusion_race_fail_post(spec: dict[str, Any], skill_kind: str, *, is_pallas: bool) -> str:
    if is_pallas:
        key = "pallas_after_fail_heal_race" if skill_kind == "heal" else "pallas_after_fail_race"
    else:
        key = "after_fail_describe_heal_race" if skill_kind == "heal" else "after_fail_describe_race"
    post = str(spec.get(key, "") or "").strip()
    if post:
        return post
    return default_intrusion_race_fail_post(skill_kind, is_pallas=is_pallas)


def duplicate_intrusion_damage_to_both(defs: list[Any]) -> list[dict[str, Any]]:
    """抢认双败时，将单目标损创效果拆为挑战者、守方各结算一次。"""
    out: list[dict[str, Any]] = []
    for raw in defs:
        if not isinstance(raw, dict):
            continue
        if raw.get("type") != "deal_damage":
            out.append(dict(raw))
            continue
        out.extend({**raw, "target": side} for side in ("challenger", "defender"))
    return out


def apply_operator_intrusion_race_fail_outcomes(
    stacks: Any,
    spec: dict[str, Any],
    kind: str,
    actor: str,
) -> None:
    """抢认无人成功：按技能表对双方落效，并结算 on_fail_effects。"""
    from src.plugins.duel.duel_round_engine import apply_effect_dicts

    on_fail = spec.get("on_fail_effects", [])
    if not isinstance(on_fail, list):
        on_fail = []
    skill_rows = select_operator_intrusion_success_effects(spec, kind)
    if kind == "heal":
        apply_effect_dicts(stacks, skill_rows, actor)
    else:
        apply_effect_dicts(stacks, duplicate_intrusion_damage_to_both(skill_rows), actor)
    apply_effect_dicts(stacks, duplicate_intrusion_damage_to_both(on_fail), actor)


async def _run_operator_intrusion_race_qte(
    matcher: Matcher,
    group_id: int,
    challenger_id: str,
    defender_id: str,
    stacks: Any,
    spec: dict[str, Any],
    actor: str,
    intrusion_ctx: dict[str, str],
    *,
    round_header: str,
    scene_card: str,
    narr_log: Any = None,
    round_index: int = 0,
    round_tag: str = "",
    bot_mode: bool = False,
    challenger_is_bot: bool = False,
    defender_is_bot: bool = False,
) -> None:
    """乱入抢认：双方抢先咏名，成功者按技能表结算（相对胜者 actor）。"""
    from src.plugins.duel.config import plugin_config
    from src.plugins.duel.duel_round_engine import (
        append_combat_delta,
        apply_effect_dicts,
        format_describe,
        snapshot_combat,
    )
    from src.plugins.duel.duel_send import (
        release_round_line_buffer,
        send_duel_line,
        send_duel_line_merge_buffer,
    )

    on_fail = spec.get("on_fail_effects", [])
    if not isinstance(on_fail, list):
        on_fail = []

    if not plugin_config.duel_compact_round:
        await release_round_line_buffer()

    window_sec = int(spec.get("window_sec", 12))
    window_sec = max(5, min(window_sec, 45))
    required_key = intrusion_ctx["name"]
    prompt_extra = str(spec.get("prompt", "")).strip()
    is_pallas = bool(intrusion_ctx.get("is_pallas"))
    prelude = str(spec.get("pallas_prelude" if is_pallas else "intrusion_prelude", "") or "").strip()
    if not prelude:
        if is_pallas:
            prelude = "<O>（<P>）落在场心，冷冷看着你们。"
        else:
            prelude = "一名 <P> 的干员闯入，止步场中。"
    prelude_out = format_describe(prelude, challenger_id, defender_id, intrusion_ctx)
    card = (
        format_describe(scene_card.strip(), challenger_id, defender_id, intrusion_ctx)
        if scene_card.strip()
        else Message()
    )
    parts: list[Message] = []
    if round_header.strip():
        parts.append(duel_plain(round_header.strip()))
    if message_has_content(card):
        parts.append(card)
    if message_has_content(prelude_out):
        parts.append(prelude_out)

    extra = duel_text(f"{prompt_extra}\n") if prompt_extra else Message()
    op_hint = f"「{required_key}」"
    if plugin_config.duel_compact_round:
        prompt = (
            extra
            + duel_text(QTE_INTRUSION_RACE_TITLE)
            + duel_at(challenger_id)
            + duel_at(defender_id)
            + duel_text(f" {window_sec}秒内抢先发送闯入者游戏内干员名{op_hint}。")
        )
    else:
        prompt = (
            extra
            + duel_text(QTE_INTRUSION_RACE_TITLE)
            + duel_at(challenger_id)
            + duel_at(defender_id)
            + duel_text(f"须在{window_sec}秒内抢先发送闯入者的游戏内干员名{op_hint}（须完全一致，勿夹他词）。")
        )
    prelude_block = duel_join_lines(*parts, sep="\n") if parts else Message()
    body = append_duel_message(prelude_block, prompt, sep="\n") if message_has_content(prelude_block) else prompt
    need_avatar = bool(spec.get("show_avatar"))
    avatar_img: bytes | None = None
    if need_avatar:
        from src.plugins.duel.arknights_ops import resolve_operator_avatar_image

        avatar_img = await resolve_operator_avatar_image(str(intrusion_ctx.get("op_id", "")))
        if not avatar_img:
            logger.error(
                f"operator_intrusion race missing local avatar op_id={intrusion_ctx.get('op_id')} "
                f"name={intrusion_ctx.get('name')}"
            )
    split_image = need_avatar and bool(avatar_img)
    delivered = False
    if need_avatar and not avatar_img:
        pass
    elif plugin_config.duel_compact_round:
        delivered = await send_duel_line_merge_buffer(
            group_id,
            body,
            matcher=matcher,
            challenger_id=challenger_id,
            defender_id=defender_id,
            bot_mode=bot_mode,
            challenger_is_bot=challenger_is_bot,
            defender_is_bot=defender_is_bot,
            image_bytes=avatar_img,
            split_image_on_fail=split_image,
        )
    else:
        delivered = await send_duel_line(
            group_id,
            body,
            matcher=matcher,
            challenger_id=challenger_id,
            defender_id=defender_id,
            bot_mode=bot_mode,
            challenger_is_bot=challenger_is_bot,
            defender_is_bot=defender_is_bot,
            immediate=True,
            image_bytes=avatar_img,
            split_image_on_fail=split_image,
        )
    if not delivered:
        logger.warning(f"operator_intrusion race prompt undelivered group={group_id}")
        snap = snapshot_combat(stacks)
        apply_effect_dicts(stacks, on_fail, actor)
        await send_duel_line(
            group_id,
            append_combat_delta(
                QTE_INTRUSION_FAIL_STUB,
                challenger_id,
                defender_id,
                snap,
                stacks,
            ),
            matcher=matcher,
            challenger_id=challenger_id,
            defender_id=defender_id,
            bot_mode=bot_mode,
            challenger_is_bot=challenger_is_bot,
            defender_is_bot=defender_is_bot,
            immediate=not plugin_config.duel_compact_round,
        )
        if narr_log is not None:
            narr_log.add(f"第{round_index}幕·{round_tag} 抢认提示未发出")
        return

    loop = asyncio.get_running_loop()
    fut: asyncio.Future[str | None] = loop.create_future()
    gid = str(group_id)
    deadline = time.time() + window_sec
    _race_sessions[gid] = _DuelRaceQteSession(
        future=fut,
        required_key=required_key,
        deadline=deadline,
        challenger_id=challenger_id,
        defender_id=defender_id,
    )
    sync_active_qte_group(gid)
    schedule_bot_race_qte_auto_answer(
        group_id,
        challenger_id,
        defender_id,
        required_key,
        fut,
        window_sec,
        qte_kind="intrusion",
    )
    winner_uid: str | None = None
    try:
        winner_uid = await asyncio.wait_for(fut, timeout=window_sec + 1.0)
    except TimeoutError:
        winner_uid = None
    finally:
        _race_sessions.pop(gid, None)
        sync_active_qte_group(gid)

    if winner_uid:
        winner_actor = actor_from_user_id(winner_uid, challenger_id, defender_id)
        kind = str(intrusion_ctx.get("picked_skill_kind") or "neutral")
        ok_fx = select_operator_intrusion_success_effects(spec, kind)
        snap = snapshot_combat(stacks)
        apply_effect_dicts(stacks, ok_fx, winner_actor)
        pb = spec.get("profession_bonus")
        prof = intrusion_ctx.get("profession", "")
        if isinstance(pb, dict) and prof in pb:
            bonus = pb[prof]
            if isinstance(bonus, list) and bonus:
                apply_effect_dicts(stacks, bonus, winner_actor)
        spb = spec.get("sub_profession_bonus")
        sub_id = intrusion_ctx.get("sub_profession_id", "")
        if isinstance(spb, dict) and sub_id and sub_id in spb:
            sbonus = spb[sub_id]
            if isinstance(sbonus, list) and sbonus:
                apply_effect_dicts(stacks, sbonus, winner_actor)
        post = str(spec.get("pallas_after_success" if is_pallas else "after_success_describe", "") or "").strip()
        if not post:
            if is_pallas:
                post = "<O> 似乎颇为得意，对 <B> 释放「<SK>」：\n<SKD>\n随即离开。"
            else:
                post = "<O> 似乎松了口气，对 <B> 释放「<SK>」：\n<SKD>\n转身离去。"
        body = append_duel_message(
            duel_at(winner_uid) + duel_text(QTE_INTRUSION_RACE_WIN_TAIL),
            format_describe(post, challenger_id, defender_id, intrusion_ctx),
        )
        if isinstance(pb, dict) and prof in pb and isinstance(pb.get(prof), list) and pb[prof]:
            body = append_duel_message(
                body,
                format_describe(
                    f"\n<O> 似乎还记着你认得{intrusion_ctx.get('profession_cn', prof)}。",
                    challenger_id,
                    defender_id,
                    intrusion_ctx,
                ),
            )
        if isinstance(spb, dict) and sub_id and sub_id in spb and isinstance(spb.get(sub_id), list) and spb[sub_id]:
            body = append_duel_message(
                body,
                format_describe("\n<O> 离去前又多施了一分力。", challenger_id, defender_id, intrusion_ctx),
            )
        await send_duel_line(
            group_id,
            append_combat_delta(body, challenger_id, defender_id, snap, stacks),
            matcher=matcher,
            challenger_id=challenger_id,
            defender_id=defender_id,
            bot_mode=bot_mode,
            challenger_is_bot=challenger_is_bot,
            defender_is_bot=defender_is_bot,
            immediate=not plugin_config.duel_compact_round,
        )
        if narr_log is not None:
            narr_log.add(f"第{round_index}幕·{round_tag} 抢认成 {required_key}")
        return

    kind = str(intrusion_ctx.get("picked_skill_kind") or "neutral")
    snap = snapshot_combat(stacks)
    apply_operator_intrusion_race_fail_outcomes(stacks, spec, kind, actor)
    post = resolve_intrusion_race_fail_post(spec, kind, is_pallas=is_pallas)
    body = append_combat_delta(
        append_duel_message(
            duel_text(QTE_INTRUSION_RACE_DRAW_TAIL),
            format_describe(post, challenger_id, defender_id, intrusion_ctx),
        ),
        challenger_id,
        defender_id,
        snap,
        stacks,
    )
    await send_duel_line(
        group_id,
        body,
        matcher=matcher,
        challenger_id=challenger_id,
        defender_id=defender_id,
        bot_mode=bot_mode,
        challenger_is_bot=challenger_is_bot,
        defender_is_bot=defender_is_bot,
        immediate=not plugin_config.duel_compact_round,
    )
    if narr_log is not None:
        narr_log.add(f"第{round_index}幕·{round_tag} 抢认败·{kind}")


async def _run_operator_intrusion_qte(
    matcher: Matcher,
    group_id: int,
    challenger_id: str,
    defender_id: str,
    stacks: Any,
    spec: dict[str, Any],
    actor: str,
    intrusion_ctx: dict[str, str] | None,
    *,
    round_header: str,
    scene_card: str,
    narr_log: Any = None,
    round_index: int = 0,
    round_tag: str = "",
    bot_mode: bool = False,
    challenger_is_bot: bool = False,
    defender_is_bot: bool = False,
) -> None:
    """乱入：唤名与施展同幕；辨认成功即结算技能并展示简述。"""
    from src.plugins.duel.config import plugin_config
    from src.plugins.duel.duel_round_engine import (
        append_combat_delta,
        apply_effect_dicts,
        format_describe,
        snapshot_combat,
    )
    from src.plugins.duel.duel_send import (
        release_round_line_buffer,
        send_duel_line,
        send_duel_line_merge_buffer,
    )

    on_fail = spec.get("on_fail_effects", [])
    if not isinstance(on_fail, list):
        on_fail = []

    if not intrusion_ctx or not intrusion_ctx.get("name"):
        logger.warning("operator_intrusion qte skipped: no operator ctx")
        snap = snapshot_combat(stacks)
        apply_effect_dicts(stacks, on_fail, actor)
        await send_duel_line(
            group_id,
            append_combat_delta(
                QTE_INTRUSION_FAIL_STUB,
                challenger_id,
                defender_id,
                snap,
                stacks,
            ),
            matcher=matcher,
            challenger_id=challenger_id,
            defender_id=defender_id,
            bot_mode=bot_mode,
            challenger_is_bot=challenger_is_bot,
            defender_is_bot=defender_is_bot,
            immediate=not plugin_config.duel_compact_round,
        )
        if narr_log is not None:
            narr_log.add(f"第{round_index}幕·{round_tag} 使者无名")
        return

    if intrusion_should_race(spec):
        await _run_operator_intrusion_race_qte(
            matcher,
            group_id,
            challenger_id,
            defender_id,
            stacks,
            spec,
            actor,
            intrusion_ctx,
            round_header=round_header,
            scene_card=scene_card,
            narr_log=narr_log,
            round_index=round_index,
            round_tag=round_tag,
            bot_mode=bot_mode,
            challenger_is_bot=challenger_is_bot,
            defender_is_bot=defender_is_bot,
        )
        return

    if not plugin_config.duel_compact_round:
        await release_round_line_buffer()

    window_sec = int(spec.get("window_sec", 12))
    window_sec = max(5, min(window_sec, 45))
    tgt = str(spec.get("target", "actor"))
    responder = resolve_qte_responder_qq(tgt, actor, challenger_id, defender_id)
    required_key = intrusion_ctx["name"]
    prompt_extra = str(spec.get("prompt", "")).strip()

    is_pallas = bool(intrusion_ctx.get("is_pallas"))
    prelude = str(spec.get("pallas_prelude" if is_pallas else "intrusion_prelude", "") or "").strip()
    if not prelude:
        if is_pallas:
            prelude = "<O>（<P>）落在场心，冷冷看着你们。"
        else:
            prelude = "一名 <P> 的干员闯入，止步场中。"
    prelude_out = format_describe(prelude, challenger_id, defender_id, intrusion_ctx)
    card = (
        format_describe(scene_card.strip(), challenger_id, defender_id, intrusion_ctx)
        if scene_card.strip()
        else Message()
    )
    parts: list[Message] = []
    if round_header.strip():
        parts.append(duel_plain(round_header.strip()))
    if message_has_content(card):
        parts.append(card)
    if message_has_content(prelude_out):
        parts.append(prelude_out)

    loop = asyncio.get_running_loop()
    fut: asyncio.Future[bool] = loop.create_future()
    sid = qte_session_id(group_id, responder)
    deadline = time.time() + window_sec

    extra = duel_text(f"{prompt_extra}\n") if prompt_extra else Message()
    if plugin_config.duel_compact_round:
        prompt = (
            extra
            + duel_text(QTE_INTRUSION_TITLE + "请")
            + duel_at(responder)
            + duel_text(f" {window_sec}秒内发送其游戏内干员名。")
        )
    else:
        prompt = (
            extra
            + duel_text(QTE_INTRUSION_TITLE + "请")
            + duel_at(responder)
            + duel_text(f"在{window_sec}秒内发送闯入者的「游戏内战显示名」（须完全一致，勿夹他词）。")
        )
    prelude_block = duel_join_lines(*parts, sep="\n") if parts else Message()
    body = append_duel_message(prelude_block, prompt, sep="\n") if message_has_content(prelude_block) else prompt
    need_avatar = bool(spec.get("show_avatar"))
    avatar_img: bytes | None = None
    if need_avatar:
        from src.plugins.duel.arknights_ops import resolve_operator_avatar_image

        avatar_img = await resolve_operator_avatar_image(str(intrusion_ctx.get("op_id", "")))
        if not avatar_img:
            logger.error(
                f"operator_intrusion missing local avatar op_id={intrusion_ctx.get('op_id')} "
                f"name={intrusion_ctx.get('name')}"
            )
    split_image = need_avatar and bool(avatar_img)
    delivered = False
    if need_avatar and not avatar_img:
        pass
    elif plugin_config.duel_compact_round:
        delivered = await send_duel_line_merge_buffer(
            group_id,
            body,
            matcher=matcher,
            challenger_id=challenger_id,
            defender_id=defender_id,
            bot_mode=bot_mode,
            challenger_is_bot=challenger_is_bot,
            defender_is_bot=defender_is_bot,
            image_bytes=avatar_img,
            split_image_on_fail=split_image,
        )
    else:
        delivered = await send_duel_line(
            group_id,
            body,
            matcher=matcher,
            challenger_id=challenger_id,
            defender_id=defender_id,
            bot_mode=bot_mode,
            challenger_is_bot=challenger_is_bot,
            defender_is_bot=defender_is_bot,
            immediate=True,
            image_bytes=avatar_img,
            split_image_on_fail=split_image,
        )
    if not delivered:
        logger.warning(f"operator_intrusion prompt undelivered group={group_id}")
        snap = snapshot_combat(stacks)
        apply_effect_dicts(stacks, on_fail, actor)
        await send_duel_line(
            group_id,
            append_combat_delta(
                QTE_INTRUSION_FAIL_STUB,
                challenger_id,
                defender_id,
                snap,
                stacks,
            ),
            matcher=matcher,
            challenger_id=challenger_id,
            defender_id=defender_id,
            bot_mode=bot_mode,
            challenger_is_bot=challenger_is_bot,
            defender_is_bot=defender_is_bot,
            immediate=not plugin_config.duel_compact_round,
        )
        if narr_log is not None:
            narr_log.add(f"第{round_index}幕·{round_tag} 提示未发出")
        return

    _sessions[sid] = _DuelQteSession(future=fut, required_key=required_key, deadline=deadline)
    sync_active_qte_group(sid[0])
    schedule_bot_qte_auto_answer(group_id, responder, required_key, fut, window_sec, qte_kind="intrusion")
    ok = False
    try:
        ok = await asyncio.wait_for(fut, timeout=window_sec + 1.0)
    except TimeoutError:
        ok = False
    finally:
        _sessions.pop(sid, None)
        sync_active_qte_group(sid[0])

    if ok:
        kind = str(intrusion_ctx.get("picked_skill_kind") or "neutral")
        ok_fx = select_operator_intrusion_success_effects(spec, kind)
        snap = snapshot_combat(stacks)
        apply_effect_dicts(stacks, ok_fx, actor)
        applied_effects: list[Any] = list(ok_fx)
        pb = spec.get("profession_bonus")
        prof = intrusion_ctx.get("profession", "")
        if isinstance(pb, dict) and prof in pb:
            bonus = pb[prof]
            if isinstance(bonus, list) and bonus:
                apply_effect_dicts(stacks, bonus, actor)
                applied_effects.extend(bonus)
        spb = spec.get("sub_profession_bonus")
        sub_id = intrusion_ctx.get("sub_profession_id", "")
        if isinstance(spb, dict) and sub_id and sub_id in spb:
            sbonus = spb[sub_id]
            if isinstance(sbonus, list) and sbonus:
                apply_effect_dicts(stacks, sbonus, actor)
                applied_effects.extend(sbonus)
        post = str(spec.get("pallas_after_success" if is_pallas else "after_success_describe", "") or "").strip()
        if not post:
            if is_pallas:
                post = "<O> 似乎颇为得意，对 <B> 释放「<SK>」：\n<SKD>\n随即离开。"
            else:
                post = "<O> 似乎松了口气，对 <B> 释放「<SK>」：\n<SKD>\n转身离去。"
        body = format_describe(post, challenger_id, defender_id, intrusion_ctx)
        if isinstance(pb, dict) and prof in pb and isinstance(pb.get(prof), list) and pb[prof]:
            body = append_duel_message(
                body,
                format_describe(
                    f"\n<O> 似乎还记着你认得{intrusion_ctx.get('profession_cn', prof)}。",
                    challenger_id,
                    defender_id,
                    intrusion_ctx,
                ),
            )
        if isinstance(spb, dict) and sub_id and sub_id in spb and isinstance(spb.get(sub_id), list) and spb[sub_id]:
            body = append_duel_message(
                body,
                format_describe("\n<O> 离去前又多施了一分力。", challenger_id, defender_id, intrusion_ctx),
            )
        await send_duel_line(
            group_id,
            append_combat_delta(
                body,
                challenger_id,
                defender_id,
                snap,
                stacks,
            ),
            matcher=matcher,
            challenger_id=challenger_id,
            defender_id=defender_id,
            bot_mode=bot_mode,
            challenger_is_bot=challenger_is_bot,
            defender_is_bot=defender_is_bot,
            immediate=not plugin_config.duel_compact_round,
        )
        if narr_log is not None:
            nm = intrusion_ctx.get("name", "")
            narr_log.add(f"第{round_index}幕·{round_tag} 辨认成 {nm}")
    else:
        kind = str(intrusion_ctx.get("picked_skill_kind") or "neutral")
        skill_fx = prepare_intrusion_fail_skill_effects(
            select_operator_intrusion_success_effects(spec, kind),
            kind,
        )
        snap = snapshot_combat(stacks)
        if skill_fx:
            apply_effect_dicts(stacks, skill_fx, actor)
        apply_effect_dicts(stacks, on_fail, actor)
        if is_pallas:
            fail_key = "pallas_after_fail_heal" if kind == "heal" else "pallas_after_fail"
        else:
            fail_key = "after_fail_describe_heal" if kind == "heal" else "after_fail_describe"
        post = str(spec.get(fail_key, "") or "").strip()
        if not post:
            post = default_intrusion_fail_post(kind, actor, is_pallas=is_pallas)
        tail = duel_at(responder) + duel_text(f" 没能认出{required_key}")
        body = append_combat_delta(
            append_duel_message(tail, format_describe(post, challenger_id, defender_id, intrusion_ctx)),
            challenger_id,
            defender_id,
            snap,
            stacks,
        )
        await send_duel_line(
            group_id,
            body,
            matcher=matcher,
            challenger_id=challenger_id,
            defender_id=defender_id,
            bot_mode=bot_mode,
            challenger_is_bot=challenger_is_bot,
            defender_is_bot=defender_is_bot,
            immediate=not plugin_config.duel_compact_round,
        )
        if narr_log is not None:
            narr_log.add(f"第{round_index}幕·{round_tag} 辨认败·{kind}")


async def _run_keyword_race_qte(
    matcher: Matcher,
    group_id: int,
    challenger_id: str,
    defender_id: str,
    stacks: Any,
    d_ev: LoadedEvent,
    actor: str,
    spec: dict[str, Any],
    *,
    round_header: str = "",
    narr_log: Any = None,
    round_index: int = 0,
    round_tag: str = "",
    bot_mode: bool = False,
    challenger_is_bot: bool = False,
    defender_is_bot: bool = False,
) -> None:
    """抢攻 QTE：双方抢先发送关键词，成功者结算 on_success（相对胜者 actor）。"""
    from src.plugins.duel.config import plugin_config
    from src.plugins.duel.duel_round_engine import (
        append_combat_delta,
        apply_effect_dicts,
        qte_actor_from_target,
        snapshot_combat,
    )
    from src.plugins.duel.duel_send import (
        release_round_line_buffer,
        send_duel_line,
        send_duel_line_merge_buffer,
    )

    keys = spec.get("keys")
    if not isinstance(keys, list) or not keys:
        logger.warning(f"duel event {d_ev.event_id} race qte.keys invalid")
        return
    valid_keys = [str(k) for k in keys if str(k).strip()]
    if not valid_keys:
        return
    window_sec = int(spec.get("window_sec", 8))
    window_sec = max(3, min(window_sec, 30))
    required_key = random.choice(valid_keys)
    prompt_extra = str(spec.get("prompt", "")).strip()
    on_ok = spec.get("on_success_effects", [])
    on_fail = spec.get("on_fail_effects", [])
    if not isinstance(on_ok, list):
        on_ok = []
    if not isinstance(on_fail, list):
        on_fail = []

    if not plugin_config.duel_compact_round:
        await release_round_line_buffer()

    loop = asyncio.get_running_loop()
    fut: asyncio.Future[str | None] = loop.create_future()
    gid = str(group_id)
    deadline = time.time() + window_sec
    damage_hint = race_qte_damage_hint(on_ok)

    extra = duel_text(f"{prompt_extra}\n") if prompt_extra else Message()
    head = duel_plain(round_header.strip()) if round_header.strip() else Message()
    if plugin_config.duel_compact_round:
        prompt = (
            extra
            + duel_text(QTE_RACE_TITLE)
            + duel_at(challenger_id)
            + duel_at(defender_id)
            + duel_text(f" {window_sec}秒内抢先发送「{required_key}」——{damage_hint}。")
        )
        line = append_duel_message(head, prompt) if message_has_content(head) else prompt
        delivered = await send_duel_line_merge_buffer(
            group_id,
            line,
            matcher=matcher,
            challenger_id=challenger_id,
            defender_id=defender_id,
            bot_mode=bot_mode,
            challenger_is_bot=challenger_is_bot,
            defender_is_bot=defender_is_bot,
        )
    else:
        prompt = (
            extra
            + duel_text(QTE_RACE_TITLE)
            + duel_at(challenger_id)
            + duel_at(defender_id)
            + duel_text(f"须在{window_sec}秒内抢先发送「{required_key}」（须完全一致）——{damage_hint}。")
        )
        line = append_duel_message(head, prompt) if message_has_content(head) else prompt
        delivered = await send_duel_line(
            group_id,
            line,
            matcher=matcher,
            challenger_id=challenger_id,
            defender_id=defender_id,
            bot_mode=bot_mode,
            challenger_is_bot=challenger_is_bot,
            defender_is_bot=defender_is_bot,
            immediate=True,
        )
    if not delivered:
        logger.warning(f"race qte prompt undelivered group={group_id} event={d_ev.event_id}")
        snap = snapshot_combat(stacks)
        fail_actor = qte_actor_from_target(spec, actor)
        apply_effect_dicts(stacks, on_fail, fail_actor)
        await send_duel_line(
            group_id,
            append_combat_delta(
                duel_text(QTE_RACE_DRAW_TAIL),
                challenger_id,
                defender_id,
                snap,
                stacks,
            ),
            matcher=matcher,
            challenger_id=challenger_id,
            defender_id=defender_id,
            bot_mode=bot_mode,
            challenger_is_bot=challenger_is_bot,
            defender_is_bot=defender_is_bot,
            immediate=not plugin_config.duel_compact_round,
        )
        if narr_log is not None and round_tag:
            narr_log.add(f"第{round_index}幕·{round_tag} 抢攻提示未发出 {d_ev.event_id}")
        return

    _race_sessions[gid] = _DuelRaceQteSession(
        future=fut,
        required_key=required_key,
        deadline=deadline,
        challenger_id=challenger_id,
        defender_id=defender_id,
    )
    sync_active_qte_group(gid)
    schedule_bot_race_qte_auto_answer(
        group_id,
        challenger_id,
        defender_id,
        required_key,
        fut,
        window_sec,
        decoy_keys=valid_keys,
    )
    winner_uid: str | None = None
    try:
        winner_uid = await asyncio.wait_for(fut, timeout=window_sec + 1.0)
    except TimeoutError:
        winner_uid = None
    finally:
        _race_sessions.pop(gid, None)
        sync_active_qte_group(gid)

    snap = snapshot_combat(stacks)
    if winner_uid:
        winner_actor = actor_from_user_id(winner_uid, challenger_id, defender_id)
        apply_effect_dicts(stacks, on_ok, winner_actor)
        line = append_combat_delta(
            duel_at(winner_uid) + duel_text(QTE_RACE_WIN_TAIL),
            challenger_id,
            defender_id,
            snap,
            stacks,
        )
        narr_note = "抢攻成"
    else:
        fail_actor = qte_actor_from_target(spec, actor)
        if on_fail:
            apply_effect_dicts(stacks, on_fail, fail_actor)
        line = append_combat_delta(
            duel_text(QTE_RACE_DRAW_TAIL),
            challenger_id,
            defender_id,
            snap,
            stacks,
        )
        narr_note = "抢攻平"
    await send_duel_line(
        group_id,
        line,
        matcher=matcher,
        challenger_id=challenger_id,
        defender_id=defender_id,
        bot_mode=bot_mode,
        challenger_is_bot=challenger_is_bot,
        defender_is_bot=defender_is_bot,
        immediate=not plugin_config.duel_compact_round,
    )
    if narr_log is not None and round_tag:
        narr_log.add(f"第{round_index}幕·{round_tag} {narr_note} {d_ev.event_id}")


async def run_event_qte_if_any(
    matcher: Matcher,
    group_id: int,
    challenger_id: str,
    defender_id: str,
    stacks: Any,
    d_ev: LoadedEvent,
    actor: str,
    *,
    intrusion_ctx: dict[str, str] | None = None,
    round_header: str = "",
    scene_card: str = "",
    narr_log: Any = None,
    round_index: int = 0,
    round_tag: str = "",
    bot_mode: bool = False,
    challenger_is_bot: bool = False,
    defender_is_bot: bool = False,
) -> None:
    """若事件带 QTE：乱入走专场（round_header/scene_card 拼首条），抢攻或单人关键词 QTE。"""
    from src.plugins.duel.config import plugin_config
    from src.plugins.duel.duel_round_engine import (
        append_combat_delta,
        apply_effect_dicts,
        snapshot_combat,
    )
    from src.plugins.duel.duel_send import (
        release_round_line_buffer,
        send_duel_line,
        send_duel_line_merge_buffer,
    )

    spec = d_ev.qte
    if not spec:
        return
    if spec.get("type") == "operator_intrusion":
        await _run_operator_intrusion_qte(
            matcher,
            group_id,
            challenger_id,
            defender_id,
            stacks,
            spec,
            actor,
            intrusion_ctx,
            round_header=round_header,
            scene_card=scene_card,
            narr_log=narr_log,
            round_index=round_index,
            round_tag=round_tag,
            bot_mode=bot_mode,
            challenger_is_bot=challenger_is_bot,
            defender_is_bot=defender_is_bot,
        )
        return

    if qte_should_race(spec, actor):
        await _run_keyword_race_qte(
            matcher,
            group_id,
            challenger_id,
            defender_id,
            stacks,
            d_ev,
            actor,
            spec,
            round_header=round_header,
            narr_log=narr_log,
            round_index=round_index,
            round_tag=round_tag,
            bot_mode=bot_mode,
            challenger_is_bot=challenger_is_bot,
            defender_is_bot=defender_is_bot,
        )
        return

    if not plugin_config.duel_compact_round:
        await release_round_line_buffer()

    keys = spec.get("keys")
    if not isinstance(keys, list) or not keys:
        logger.warning(f"duel event {d_ev.event_id} qte.keys invalid")
        return
    valid_keys = [str(k) for k in keys if str(k).strip()]
    if not valid_keys:
        return
    window_sec = int(spec.get("window_sec", 8))
    window_sec = max(3, min(window_sec, 30))
    tgt = str(spec.get("target", "actor"))
    responder = resolve_qte_responder_qq(tgt, actor, challenger_id, defender_id)
    required_key = random.choice(valid_keys)
    prompt_extra = str(spec.get("prompt", "")).strip()
    on_ok = spec.get("on_success_effects", [])
    on_fail = spec.get("on_fail_effects", [])
    if not isinstance(on_ok, list):
        on_ok = []
    if not isinstance(on_fail, list):
        on_fail = []

    loop = asyncio.get_running_loop()
    fut: asyncio.Future[bool] = loop.create_future()
    sid = qte_session_id(group_id, responder)
    deadline = time.time() + window_sec

    extra = duel_text(f"{prompt_extra}\n") if prompt_extra else Message()
    head = duel_plain(round_header.strip()) if round_header.strip() else Message()
    if plugin_config.duel_compact_round:
        prompt = (
            extra
            + duel_text(QTE_KEYWORD_TITLE + "请")
            + duel_at(responder)
            + duel_text(f" {window_sec}秒内发「{required_key}」。")
        )
        line = append_duel_message(head, prompt) if message_has_content(head) else prompt
        delivered = await send_duel_line_merge_buffer(
            group_id,
            line,
            matcher=matcher,
            challenger_id=challenger_id,
            defender_id=defender_id,
            bot_mode=bot_mode,
            challenger_is_bot=challenger_is_bot,
            defender_is_bot=defender_is_bot,
        )
    else:
        prompt = (
            extra
            + duel_text("请")
            + duel_at(responder)
            + duel_text(f"在{window_sec}秒内发送「{required_key}」完成 QTE")
        )
        line = append_duel_message(head, prompt) if message_has_content(head) else prompt
        delivered = await send_duel_line(
            group_id,
            line,
            matcher=matcher,
            challenger_id=challenger_id,
            defender_id=defender_id,
            bot_mode=bot_mode,
            challenger_is_bot=challenger_is_bot,
            defender_is_bot=defender_is_bot,
            immediate=True,
        )
    if not delivered:
        logger.warning(f"keyword qte prompt undelivered group={group_id} event={d_ev.event_id}")
        snap = snapshot_combat(stacks)
        apply_effect_dicts(stacks, on_fail, actor)
        await send_duel_line(
            group_id,
            append_combat_delta(
                duel_at(responder) + duel_text(QTE_FAIL_TAIL),
                challenger_id,
                defender_id,
                snap,
                stacks,
            ),
            matcher=matcher,
            challenger_id=challenger_id,
            defender_id=defender_id,
            bot_mode=bot_mode,
            challenger_is_bot=challenger_is_bot,
            defender_is_bot=defender_is_bot,
            immediate=not plugin_config.duel_compact_round,
        )
        if narr_log is not None and round_tag:
            narr_log.add(f"第{round_index}幕·{round_tag} QTE提示未发出 {d_ev.event_id}")
        return

    _sessions[sid] = _DuelQteSession(future=fut, required_key=required_key, deadline=deadline)
    sync_active_qte_group(sid[0])
    schedule_bot_qte_auto_answer(
        group_id,
        responder,
        required_key,
        fut,
        window_sec,
        qte_kind="keyword",
        decoy_keys=valid_keys,
    )
    ok = False
    try:
        ok = await asyncio.wait_for(fut, timeout=window_sec + 1.0)
    except TimeoutError:
        ok = False
    finally:
        _sessions.pop(sid, None)
        sync_active_qte_group(sid[0])

    snap = snapshot_combat(stacks)
    if ok:
        apply_effect_dicts(stacks, on_ok, actor)
        line = append_combat_delta(
            duel_at(responder) + duel_text(QTE_SUCCESS_TAIL),
            challenger_id,
            defender_id,
            snap,
            stacks,
        )
    else:
        apply_effect_dicts(stacks, on_fail, actor)
        line = append_combat_delta(
            duel_at(responder) + duel_text(QTE_FAIL_TAIL),
            challenger_id,
            defender_id,
            snap,
            stacks,
        )
    await send_duel_line(
        group_id,
        line,
        matcher=matcher,
        challenger_id=challenger_id,
        defender_id=defender_id,
        bot_mode=bot_mode,
        challenger_is_bot=challenger_is_bot,
        defender_is_bot=defender_is_bot,
        immediate=not plugin_config.duel_compact_round,
    )
    if narr_log is not None and round_tag:
        narr_log.add(f"第{round_index}幕·{round_tag} QTE{'成' if ok else '败'} {d_ev.event_id}")


def clear_all_duel_qte_sessions() -> int:
    """决斗中断或重载时清空未决 QTE，返回被关闭的会话数。"""
    n = 0
    gids = (
        set(_race_sessions.keys())
        | {g for g, _ in _sessions}
        | set(_active_qte_groups)
        | set(_published_greeting_snapshot)
        | set(_cluster_qte_users)
    )
    for sid, sess in list(_sessions.items()):
        if not sess.future.done():
            sess.future.set_result(False)
            n += 1
        _sessions.pop(sid, None)
    for gid, race in list(_race_sessions.items()):
        if not race.future.done():
            race.future.set_result(None)
            n += 1
        _race_sessions.pop(gid, None)
    _active_qte_groups.clear()
    _active_qte_users_by_group.clear()
    _cluster_qte_users.clear()
    _cluster_qte_deadline.clear()
    _published_greeting_snapshot.clear()
    from src.platform.shard.registry.config import is_sharding_active

    if is_sharding_active():
        from src.platform.shard.coord.duel_qte_redis import clear_duel_qte_greeting_redis_sync

        for gid in gids:
            clear_duel_qte_greeting_redis_sync(str(gid))
    return n
