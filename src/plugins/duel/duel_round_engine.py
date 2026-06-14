from __future__ import annotations

import asyncio
import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from nonebot import logger
from nonebot.adapters import Bot  # noqa: TC002
from nonebot.adapters.onebot.v11 import Message
from nonebot.matcher import Matcher  # noqa: TC002

from src.foundation.config import GroupConfig
from src.platform.multi_bot.group import claim_group_message_event, try_acquire_group_broadcast_slot
from src.plugins.duel.config import plugin_config
from src.plugins.duel.duel_labels import bind_duel_labels, duel_label_for, reset_duel_labels, resolve_duel_labels
from src.plugins.duel.duel_message import (
    append_duel_message,
    apply_ab_placeholders,
    coerce_duel_message,
    duel_at,
    duel_join_blocks,
    duel_join_lines,
    duel_join_spaced,
    duel_plain,
    duel_text,
    message_has_content,
)
from src.plugins.duel.duel_terms import (
    CLASH_SILENT_ATTACKER,
    CLASH_SILENT_DEFENDER,
    PUBLIC_ROUND_EMPTY,
    ROUND_KIND_CLASH,
    ROUND_KIND_PUBLIC,
    STACK_BUFF,
    STACK_DEBUFF,
    STAT_DP,
    STAT_HP,
    TAG_CLASH_ATTACK,
    TAG_CLASH_DEFEND,
    TAG_CLASH_INTRUSION_ATTACK,
    TAG_CLASH_INTRUSION_DEFEND,
    TAG_EXCHANGE,
    TAG_PUBLIC,
    TAG_PUBLIC_INTRUSION,
    round_finale_head,
)

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import GroupMessageEvent

Actor = Literal["challenger", "defender"]
PoolName = Literal["public", "challenger", "defender", "exchange"]

STACK_CAP_SELF_BUFF = 4
STACK_CAP_SELF_DEBUFF = 4
STACK_CAP_FIELD = 3
COMBAT_START_HP = 20
COMBAT_MAX_DP = 5
# 场地层数：双方 deal_damage 额外 +场；heal_hp 额外 +场；add_field 时双方各 +叠层 DP


@dataclass
class DuelStacks:
    """双方 HP/DP、神恩损创与场地层数。"""

    challenger_hp: int = COMBAT_START_HP
    defender_hp: int = COMBAT_START_HP
    challenger_dp: int = 0
    defender_dp: int = 0
    challenger_buff: int = 0
    challenger_debuff: int = 0
    defender_buff: int = 0
    defender_debuff: int = 0
    field: int = 0

    def clamp(self) -> None:
        """裁剪到各栈上限。"""
        self.challenger_hp = max(0, self.challenger_hp)
        self.defender_hp = max(0, self.defender_hp)
        self.challenger_dp = max(0, min(COMBAT_MAX_DP, self.challenger_dp))
        self.defender_dp = max(0, min(COMBAT_MAX_DP, self.defender_dp))
        self.challenger_buff = max(0, min(STACK_CAP_SELF_BUFF, self.challenger_buff))
        self.challenger_debuff = max(0, min(STACK_CAP_SELF_DEBUFF, self.challenger_debuff))
        self.defender_buff = max(0, min(STACK_CAP_SELF_BUFF, self.defender_buff))
        self.defender_debuff = max(0, min(STACK_CAP_SELF_DEBUFF, self.defender_debuff))
        self.field = max(0, min(STACK_CAP_FIELD, self.field))

    def is_ko(self) -> bool:
        return self.challenger_hp <= 0 or self.defender_hp <= 0


@dataclass
class DuelNarrativeLog:
    """整场短句提要，供终幕复盘。"""

    lines: list[str] = field(default_factory=list)

    def add(self, line: str, *, max_lines: int = 12, max_len: int = 48) -> None:
        """追加一行，超长截断，条数过多时丢最旧。"""
        t = " ".join(line.replace("\n", " ").split()).strip()
        if not t:
            return
        if len(t) > max_len:
            t = t[: max_len - 1] + "…"
        self.lines.append(t)
        while len(self.lines) > max_lines:
            self.lines.pop(0)


@dataclass
class LoadedEvent:
    """单条事件：文案、即时效果、可选 QTE、可选伤害骰。"""

    event_id: str
    weight: int
    describe: str
    effects: list[dict[str, Any]]
    qte: dict[str, Any] | None = None
    damage_min: int = 0
    damage_max: int = 0
    damage2_min: int = 0
    damage2_max: int = 0


DUEL_GROUP_COOLDOWN_KEY = "duel"
DUEL_USER_REPLY_TTL_SEC = 3.0
DuelCommandGate = Literal["ok", "busy", "cooldown"]


async def try_claim_duel_message(event: GroupMessageEvent) -> bool:
    """同一条群消息仅一只牛走完整指令处理；含 message_time 以免多场八角笼共用抢占。"""
    return await claim_group_message_event(
        "duel",
        event,
        int(event.self_id),
        include_message_time=True,
    )


async def try_claim_duel_user_reply(group_id: int, *, ttl_sec: float | None = None) -> bool:
    """多 Bot 同群：短时内仅一只牛发决斗入口类提示，避免复读。"""
    sec = ttl_sec if ttl_sec is not None else DUEL_USER_REPLY_TTL_SEC
    return await try_acquire_group_broadcast_slot("duel", group_id, ttl_sec=sec)


def try_begin_duel_group(group_id: int) -> bool:
    """同群同时进行中的决斗至多一场。"""
    from src.platform.shard.coord.duel_group import try_begin_duel_group as acquire

    return acquire(group_id)


def end_duel_group(group_id: int) -> None:
    """释放群决斗占用。"""
    from src.platform.shard.coord.duel_group import end_duel_group as release

    release(group_id)


async def begin_duel_command(group_id: int) -> DuelCommandGate:
    """群级互斥 + 群级指令 CD（多 Bot 共用）。"""
    from src.platform.shard.coord.duel_group import _LOCK
    from src.plugins.duel.duel_session import get_duel_pair

    gate = await _LOCK.begin(group_id, local_alive=lambda: get_duel_pair(group_id))
    if gate == "busy":
        return "busy"
    group_cfg = GroupConfig(group_id, cooldown=plugin_config.duel_bot_cooldown_sec)
    if not await group_cfg.is_cooldown(DUEL_GROUP_COOLDOWN_KEY):
        end_duel_group(group_id)
        return "cooldown"
    await group_cfg.refresh_cooldown(DUEL_GROUP_COOLDOWN_KEY)
    return "ok"


def _event_pack_dir() -> Path:
    """默认事件包目录。"""
    return Path(__file__).resolve().parent / "event_packs" / "default"


def _pick_weighted(
    events: list[LoadedEvent],
    *,
    qte_mult: float = 1.0,
    weight_mult: float = 1.0,
) -> LoadedEvent | None:
    """按 weight 加权随机；带 qte 的事件可乘 qte_mult，全池可乘 weight_mult。"""
    if not events:
        return None

    def eff_weight(e: LoadedEvent) -> int:
        w = max(0, int(e.weight * weight_mult))
        if qte_mult > 1.0 and e.qte:
            return int(w * qte_mult)
        return w

    total = sum(eff_weight(e) for e in events)
    if total <= 0:
        return random.choice(events)
    r = random.randint(1, total)
    acc = 0
    for e in events:
        acc += eff_weight(e)
        if r <= acc:
            return e
    return events[-1]


def apply_hp_damage(stacks: DuelStacks, target: Actor, raw: int) -> int:
    """扣 HP，先扣 DP 再扣血；场地层数额外增加损创。"""
    raw = max(0, int(raw)) + stacks.field
    if target == "challenger":
        dp = stacks.challenger_dp
        if dp > 0 and raw > 0:
            absorb = min(dp, raw)
            stacks.challenger_dp -= absorb
            raw -= absorb
        stacks.challenger_hp -= raw
        return raw
    dp = stacks.defender_dp
    if dp > 0 and raw > 0:
        absorb = min(dp, raw)
        stacks.defender_dp -= absorb
        raw -= absorb
    stacks.defender_hp -= raw
    return raw


def _parse_qte(raw: dict[str, Any] | None, eid: str) -> dict[str, Any] | None:
    """解析 QTE 配置；干员乱入不要求 keys。"""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        logger.warning(f"duel event {eid} qte must be object, ignored")
        return None
    if raw.get("type") == "operator_intrusion":
        return raw
    keys = raw.get("keys")
    if not isinstance(keys, list) or not keys:
        logger.warning(f"duel event {eid} qte.keys missing or empty, ignored")
        return None
    if not all(isinstance(x, (str, int, float)) for x in keys):
        logger.warning(f"duel event {eid} qte.keys invalid types, ignored")
        return None
    return raw


def event_needs_ark_context(ev: LoadedEvent) -> bool:
    """是否需要随机六星干员占位数据。"""
    if ev.qte and ev.qte.get("type") == "operator_intrusion":
        return True
    if any(
        x in ev.describe
        for x in ("<O>", "<P>", "<S1>", "<S2>", "<S3>", "<S1D>", "<S2D>", "<S3D>", "<SK>", "<SKD>", "<SKL>")
    ):
        return True
    q = ev.qte
    if not q:
        return False
    ph = ("<O>", "<P>", "<S1>", "<S2>", "<S3>", "<S1D>", "<S2D>", "<S3D>", "<SK>", "<SKD>", "<SKL>")
    for k in ("intrusion_prelude", "after_success_describe", "after_fail_describe"):
        t = str(q.get(k, "") or "")
        if any(x in t for x in ph):
            return True
    return False


def _parse_damage_range(raw_val: Any) -> tuple[int, int]:
    """解析 damage / damage2：整数或 [min, max]。"""
    if isinstance(raw_val, list) and len(raw_val) >= 2:
        lo, hi = int(raw_val[0]), int(raw_val[1])
    elif isinstance(raw_val, int):
        lo, hi = raw_val, raw_val
    else:
        return 0, 0
    if lo > hi:
        lo, hi = hi, lo
    return max(0, lo), max(0, hi)


def _parse_event(raw: dict[str, Any], pool: PoolName) -> LoadedEvent | None:
    """单条 JSON 对象 → LoadedEvent。"""
    try:
        eid = str(raw["id"])
        weight = int(raw.get("weight", 1))
        desc = str(raw["describe"])
        eff = raw.get("effects", [])
        if not isinstance(eff, list):
            return None
        qte = _parse_qte(raw.get("qte"), eid)
        d1_lo, d1_hi = _parse_damage_range(raw.get("damage", 0))
        d2_lo, d2_hi = _parse_damage_range(raw.get("damage2", 0))
        return LoadedEvent(
            event_id=eid,
            weight=max(0, weight),
            describe=desc,
            effects=eff,
            qte=qte,
            damage_min=d1_lo,
            damage_max=d1_hi,
            damage2_min=d2_lo,
            damage2_max=d2_hi,
        )
    except (KeyError, TypeError, ValueError) as err:
        logger.warning(f"duel event parse skip pool={pool}: {err}")
        return None


_pools_cache: dict[PoolName, list[LoadedEvent]] | None = None


def _read_event_pools_from_disk() -> dict[PoolName, list[LoadedEvent]]:
    """读入 public / challenger / defender / exchange 四个池。"""
    base = _event_pack_dir()
    pools: dict[PoolName, list[LoadedEvent]] = {
        "public": [],
        "challenger": [],
        "defender": [],
        "exchange": [],
    }
    mapping: list[tuple[PoolName, str]] = [
        ("public", "public.json"),
        ("challenger", "challenger.json"),
        ("defender", "defender.json"),
        ("exchange", "exchange.json"),
    ]
    for pool, fname in mapping:
        path = base / fname
        if not path.is_file():
            logger.warning(f"duel event pack missing: {path}")
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as err:
            logger.error(f"duel event pack load fail {path}: {err}")
            continue
        if not isinstance(data, list):
            logger.warning(f"duel event pack not a list: {path}")
            continue
        for item in data:
            if isinstance(item, dict):
                parsed = _parse_event(item, pool)
                if parsed:
                    pools[pool].append(parsed)
    return pools


def get_event_pools() -> dict[PoolName, list[LoadedEvent]]:
    """返回缓存的事件池（未加载则读盘）。"""
    global _pools_cache
    if _pools_cache is None:
        _pools_cache = _read_event_pools_from_disk()
    return _pools_cache


def load_event_pools() -> dict[PoolName, list[LoadedEvent]]:
    """同 get_event_pools（兼容旧名）。"""
    return get_event_pools()


def reload_event_pools() -> str:
    """热重载事件池与干员表，并清空未决 QTE。"""
    from src.plugins.duel.arknights_ops import get_operators_payload, reload_operators_cache
    from src.plugins.duel.duel_qte import clear_all_duel_qte_sessions

    clear_all_duel_qte_sessions()
    reload_operators_cache()
    global _pools_cache
    _pools_cache = _read_event_pools_from_disk()
    n = sum(len(v) for v in _pools_cache.values())
    payload = get_operators_payload()
    ops = payload.get("operators")
    oc = len(ops) if isinstance(ops, list) else 0
    return (
        f"节庆剧目表已重载，共 {n} 条（{ROUND_KIND_PUBLIC} {len(_pools_cache['public'])} / "
        f"{TAG_EXCHANGE} {len(_pools_cache['exchange'])} / "
        f"攻方 {len(_pools_cache['challenger'])} / 守方 {len(_pools_cache['defender'])}）。\n"
        f"异邦使者名录：{oc} 名（resource/arknights/operators_6star.json）。"
    )


def _resolve_subject(target: str, actor: Actor) -> list[Actor]:
    """效果 target 字段 → 作用在哪些 side。"""
    if target in ("actor", "self"):
        return [actor]
    if target == "challenger":
        return ["challenger"]
    if target == "defender":
        return ["defender"]
    if target == "both":
        return ["challenger", "defender"]
    if target == "other":
        return ["defender"] if actor == "challenger" else ["challenger"]
    logger.warning(f"duel unknown effect target={target!r}, ignored")
    return []


def _effect_value_from_damage(eff: dict[str, Any], dmg1: int | None, dmg2: int | None) -> int:
    """use_damage 为 true 用 <DMG>，为 damage2 用 <DMG2>。"""
    flag = eff.get("use_damage")
    if not flag:
        return int(eff.get("value", 0))
    src = dmg2 if flag in ("damage2", "2", "DMG2") else dmg1
    return max(1, int(src or 1))


def _apply_effect(
    stacks: DuelStacks,
    eff: dict[str, Any],
    actor: Actor,
    *,
    dmg1: int | None = None,
    dmg2: int | None = None,
) -> None:
    """应用单条效果字典。"""
    etype = eff.get("type")
    value = _effect_value_from_damage(eff, dmg1, dmg2) if eff.get("use_damage") else int(eff.get("value", 0))
    tgt = str(eff.get("target", "actor"))

    if etype == "add_field":
        stacks.field += value
        stacks.challenger_dp = min(COMBAT_MAX_DP, stacks.challenger_dp + value)
        stacks.defender_dp = min(COMBAT_MAX_DP, stacks.defender_dp + value)
    elif etype == "add_self_buff":
        for sub in _resolve_subject(tgt, actor):
            if sub == "challenger":
                stacks.challenger_buff += value
            else:
                stacks.defender_buff += value
    elif etype == "add_self_debuff":
        for sub in _resolve_subject(tgt, actor):
            if sub == "challenger":
                stacks.challenger_debuff += value
            else:
                stacks.defender_debuff += value
    elif etype == "deal_damage":
        dealt = max(1, value) if value > 0 else 0
        for sub in _resolve_subject(tgt, actor):
            apply_hp_damage(stacks, sub, dealt)
    elif etype == "add_dp":
        for sub in _resolve_subject(tgt, actor):
            if sub == "challenger":
                stacks.challenger_dp += value
            else:
                stacks.defender_dp += value
    elif etype == "heal_hp":
        heal = value + stacks.field
        for sub in _resolve_subject(tgt, actor):
            if sub == "challenger":
                stacks.challenger_hp = min(COMBAT_START_HP, stacks.challenger_hp + heal)
            else:
                stacks.defender_hp = min(COMBAT_START_HP, stacks.defender_hp + heal)
    else:
        logger.warning(f"duel unknown effect type={etype!r}, ignored")

    stacks.clamp()


def apply_effect_dicts(
    stacks: DuelStacks,
    defs: list[Any],
    actor: Actor,
    *,
    dmg1: int | None = None,
    dmg2: int | None = None,
) -> None:
    """连续应用多条效果。"""
    for eff in defs:
        if isinstance(eff, dict):
            _apply_effect(stacks, eff, actor, dmg1=dmg1, dmg2=dmg2)
    stacks.clamp()


def roll_event_damages(ev: LoadedEvent) -> tuple[int | None, int | None]:
    """按事件配置掷 <DMG> / <DMG2>。"""
    dmg1 = None
    dmg2 = None
    if ev.damage_max > 0 or ev.damage_min > 0:
        lo = ev.damage_min or 1
        hi = ev.damage_max or lo
        dmg1 = random.randint(lo, hi)
    if ev.damage2_max > 0 or ev.damage2_min > 0:
        lo = ev.damage2_min or 1
        hi = ev.damage2_max or lo
        dmg2 = random.randint(lo, hi)
    return dmg1, dmg2


def damage_placeholders(dmg1: int | None, dmg2: int | None) -> dict[str, int]:
    """format_describe 用的伤害占位。"""
    out: dict[str, int] = {}
    if dmg1 is not None:
        out["DMG"] = dmg1
    if dmg2 is not None:
        out["DMG2"] = dmg2
    return out


def apply_event_effects(stacks: DuelStacks, event: LoadedEvent, actor: Actor) -> None:
    """应用事件自带的 effects 列表。"""
    apply_effect_dicts(stacks, event.effects, actor)


@dataclass(frozen=True)
class CombatSnapshot:
    challenger_hp: int
    defender_hp: int
    challenger_dp: int
    defender_dp: int
    challenger_buff: int = 0
    defender_buff: int = 0
    challenger_debuff: int = 0
    defender_debuff: int = 0
    field: int = 0


def snapshot_combat(stacks: DuelStacks) -> CombatSnapshot:
    return CombatSnapshot(
        challenger_hp=stacks.challenger_hp,
        defender_hp=stacks.defender_hp,
        challenger_dp=stacks.challenger_dp,
        defender_dp=stacks.defender_dp,
        challenger_buff=stacks.challenger_buff,
        defender_buff=stacks.defender_buff,
        challenger_debuff=stacks.challenger_debuff,
        defender_debuff=stacks.defender_debuff,
        field=stacks.field,
    )


def hp_dp_changed(before: CombatSnapshot, stacks: DuelStacks) -> bool:
    """本段是否改动了双方 HP 或 DP（用于兵刃后是否省略交锋台词）。"""
    return (
        stacks.challenger_hp != before.challenger_hp
        or stacks.defender_hp != before.defender_hp
        or stacks.challenger_dp != before.challenger_dp
        or stacks.defender_dp != before.defender_dp
    )


def primary_hp_loss_side(before: CombatSnapshot, stacks: DuelStacks) -> Actor | None:
    """本段 HP 损失更多的一方（兵刃拆招的受击方）；双方无损创则 None。"""
    ch_loss = before.challenger_hp - stacks.challenger_hp
    def_loss = before.defender_hp - stacks.defender_hp
    if ch_loss <= 0 and def_loss <= 0:
        return None
    if ch_loss > def_loss:
        return "challenger"
    if def_loss > ch_loss:
        return "defender"
    return random.choice(["challenger", "defender"])


def qte_actor_from_target(spec: dict[str, Any], actor: Actor) -> Actor:
    """将 qte.target 映射为效果里的 actor（challenger/defender）。"""
    tgt = str(spec.get("target", "actor"))
    if tgt == "challenger":
        return "challenger"
    if tgt == "defender":
        return "defender"
    if tgt in ("actor", "self"):
        return actor
    if tgt == "other":
        return "defender" if actor == "challenger" else "challenger"
    return actor


def _delta_token(current: int, previous: int, label: str) -> str:
    diff = current - previous
    if diff == 0:
        return ""
    if diff > 0:
        return f"{label}+{diff}"
    return f"{label}{diff}"


def format_player_stat_lines(
    qq: str,
    hp: int,
    dp: int,
    *,
    hp_before: int | None = None,
    dp_before: int | None = None,
) -> Message:
    """单方 HP / DP；提供 hp_before/dp_before 时在括号内标本幕变动。"""
    hp_part = f"{STAT_HP} {hp}"
    if hp_before is not None:
        hp_delta = hp - hp_before
        if hp_delta != 0:
            hp_part += f" ({hp_delta:+d})"
    dp_part = f"{STAT_DP} {dp}"
    if dp_before is not None:
        dp_delta = dp - dp_before
        if dp_delta != 0:
            dp_part += f" ({dp_delta:+d})"
    return duel_plain(f"{duel_label_for(qq)} {hp_part} {dp_part}")


def side_stack_delta_line(qq: str, buff: int, buff0: int, debuff: int, debuff0: int) -> Message:
    """单方本段战意/蚀势层变动（生机/护幕由 format_combat_delta_block 另算）。"""
    tokens: list[str] = []
    for cur, prev, label in ((buff, buff0, STACK_BUFF), (debuff, debuff0, STACK_DEBUFF)):
        t = _delta_token(cur, prev, label)
        if t:
            tokens.append(t)
    if not tokens:
        return Message()
    return duel_plain(f"{duel_label_for(qq)} " + " ".join(tokens))


def player_stat_changed(
    hp: int,
    hp0: int,
    dp: int,
    dp0: int,
    buff: int,
    buff0: int,
    debuff: int,
    debuff0: int,
) -> bool:
    return hp != hp0 or dp != dp0 or buff != buff0 or debuff != debuff0


def format_combat_delta_block(
    challenger_id: str,
    defender_id: str,
    before: CombatSnapshot,
    stacks: DuelStacks,
) -> Message:
    """本段数值变动：HP/DP（当前值+括号变动）、神恩/损创。"""
    parts: list[Message] = []
    ch_changed = player_stat_changed(
        stacks.challenger_hp,
        before.challenger_hp,
        stacks.challenger_dp,
        before.challenger_dp,
        stacks.challenger_buff,
        before.challenger_buff,
        stacks.challenger_debuff,
        before.challenger_debuff,
    )
    def_changed = player_stat_changed(
        stacks.defender_hp,
        before.defender_hp,
        stacks.defender_dp,
        before.defender_dp,
        stacks.defender_buff,
        before.defender_buff,
        stacks.defender_debuff,
        before.defender_debuff,
    )
    if ch_changed:
        parts.append(
            format_player_stat_lines(
                challenger_id,
                stacks.challenger_hp,
                stacks.challenger_dp,
                hp_before=before.challenger_hp,
                dp_before=before.challenger_dp,
            )
        )
    if def_changed:
        parts.append(
            format_player_stat_lines(
                defender_id,
                stacks.defender_hp,
                stacks.defender_dp,
                hp_before=before.defender_hp,
                dp_before=before.defender_dp,
            )
        )

    parts.extend(
        line
        for line in (
            side_stack_delta_line(
                challenger_id,
                stacks.challenger_buff,
                before.challenger_buff,
                stacks.challenger_debuff,
                before.challenger_debuff,
            ),
            side_stack_delta_line(
                defender_id,
                stacks.defender_buff,
                before.defender_buff,
                stacks.defender_debuff,
                before.defender_debuff,
            ),
        )
        if message_has_content(line)
    )

    return duel_join_spaced(*parts)


def append_combat_delta(
    narrative: str | Message,
    challenger_id: str,
    defender_id: str,
    before: CombatSnapshot,
    stacks: DuelStacks,
) -> Message:
    """在剧目文案后追加本段 HP/DP 变动（紧凑幕由幕末统一展示）。"""
    base = coerce_duel_message(narrative)
    if plugin_config.duel_compact_round:
        return base
    delta = format_combat_delta_block(challenger_id, defender_id, before, stacks)
    if not message_has_content(delta):
        return base
    return append_duel_message(base, delta, sep="\n")


def format_describe(
    template: str,
    challenger_id: str,
    defender_id: str,
    ark: dict[str, str] | None = None,
    *,
    nums: dict[str, int] | None = None,
) -> Message:
    """替换 <A><B>、<DMG> 与干员占位符。"""
    t = template
    if nums:
        for key, val in nums.items():
            t = t.replace(f"<{key}>", str(val))
    if ark:
        for token, field in (
            ("<O>", "name"),
            ("<P>", "profession_cn"),
            ("<S1>", "skill1_name"),
            ("<S2>", "skill2_name"),
            ("<S3>", "skill3_name"),
            ("<S1D>", "skill1_desc"),
            ("<S2D>", "skill2_desc"),
            ("<S3D>", "skill3_desc"),
            ("<SK>", "picked_skill_name"),
            ("<SKD>", "picked_skill_desc"),
            ("<SKL>", "picked_skill_label"),
            ("<SKK>", "picked_skill_kind_cn"),
        ):
            default = "？？？" if field == "name" else ""
            t = t.replace(token, ark.get(field, default))
    return apply_ab_placeholders(t, challenger_id, defender_id)


def format_describe_with_combat(
    template: str,
    challenger_id: str,
    defender_id: str,
    stacks: DuelStacks,
    ark: dict[str, str] | None = None,
    *,
    nums: dict[str, int] | None = None,
) -> Message:
    """替换 HP/DP 与伤害等占位。"""
    combat_nums = {
        "AHP": stacks.challenger_hp,
        "BHP": stacks.defender_hp,
        "ADP": stacks.challenger_dp,
        "BDP": stacks.defender_dp,
        "场": stacks.field,
    }
    if nums:
        combat_nums.update(nums)
    return format_describe(template, challenger_id, defender_id, ark, nums=combat_nums)


def run_round_plan(total_rounds: int) -> list[Literal["public", "clash"]]:
    """生成公共/交锋幕序列。"""
    plan: list[Literal["public", "clash"]] = []
    for _ in range(total_rounds):
        if random.random() < plugin_config.duel_public_round_weight:
            plan.append("public")
        else:
            plan.append("clash")
    return plan


def format_round_status_line(
    challenger_id: str,
    defender_id: str,
    stacks: DuelStacks,
    *,
    round_start: CombatSnapshot | None = None,
) -> Message:
    """双方 HP/DP 简报（附在本幕 flush 末尾；round_start 用于括号标本幕变动）。"""
    hp0_a = round_start.challenger_hp if round_start else None
    dp0_a = round_start.challenger_dp if round_start else None
    hp0_b = round_start.defender_hp if round_start else None
    dp0_b = round_start.defender_dp if round_start else None
    return duel_join_lines(
        format_player_stat_lines(
            challenger_id,
            stacks.challenger_hp,
            stacks.challenger_dp,
            hp_before=hp0_a,
            dp_before=dp0_a,
        ),
        format_player_stat_lines(
            defender_id,
            stacks.defender_hp,
            stacks.defender_dp,
            hp_before=hp0_b,
            dp_before=dp0_b,
        ),
    )


def summarize_winner(
    challenger_id: str,
    defender_id: str,
    stacks: DuelStacks,
    *,
    total_rounds: int,
    ko: bool = False,
) -> Message:
    """终幕：以 HP 定胜负。"""
    chp, dhp = stacks.challenger_hp, stacks.defender_hp
    head = duel_text(f"{round_finale_head(total_rounds)}。")
    if chp <= 0 and dhp <= 0:
        tag = duel_text("双方斗士")
        tail = duel_text("双方力竭，同归沉寂。")
    elif chp <= 0:
        tag = duel_text(duel_label_for(defender_id))
        tail = duel_text("令对手力竭倒地，胜局已定。" if ko else "战芒更盛。")
    elif dhp <= 0:
        tag = duel_text(duel_label_for(challenger_id))
        tail = duel_text("令对手力竭倒地，胜局已定。" if ko else "战芒更盛。")
    elif chp > dhp:
        tag = duel_text(duel_label_for(challenger_id))
        tail = duel_text("战芒更盛，双月似为其而明。")
    elif dhp > chp:
        tag = duel_text(duel_label_for(defender_id))
        tail = duel_text("战芒更盛，双月似为其而明。")
    else:
        tag = duel_text("双方斗士")
        tail = duel_text("势均力敌，撤出擂台。")
    return head + tag + tail


def _maybe_pick_ark_ctx(ev: LoadedEvent) -> dict[str, str] | None:
    """若本事件需要，则随机一名干员并生成占位上下文。"""
    if not event_needs_ark_context(ev):
        return None
    from src.plugins.duel.arknights_ops import (
        PALLAS_OPERATOR_NAME,
        build_intrusion_ctx,
        find_operator_by_name,
        pick_operator_for_intrusion,
    )

    if ev.event_id == "public_pallas_intrusion":
        op = find_operator_by_name(PALLAS_OPERATOR_NAME)
    else:
        op = pick_operator_for_intrusion(pallas_chance=plugin_config.duel_intrusion_pallas_roll_chance)
    if not op:
        return None
    return build_intrusion_ctx(op)


async def run_exchange_bout(
    matcher: Matcher,
    group_id: int,
    challenger_id: str,
    defender_id: str,
    stacks: DuelStacks,
    exchange_pool: list[LoadedEvent],
    narr: DuelNarrativeLog,
    round_index: int,
    *,
    bot_mode: bool,
    challenger_is_bot: bool,
    defender_is_bot: bool,
) -> bool:
    """兵刃交锋：双方共用对击；可附带 QTE。若本段改动了 HP/DP 则返回 True。"""
    from src.plugins.duel.duel_qte import build_exchange_auto_qte, run_event_qte_if_any
    from src.plugins.duel.duel_send import send_duel_line

    ev = _pick_weighted(exchange_pool, qte_mult=plugin_config.duel_qte_event_weight_mult)
    if not ev:
        return False
    dmg1, dmg2 = roll_event_damages(ev)
    snap = snapshot_combat(stacks)
    apply_effect_dicts(stacks, ev.effects, "challenger", dmg1=dmg1, dmg2=dmg2)
    exchange_changed_hp_dp = hp_dp_changed(snap, stacks)
    line = append_combat_delta(
        format_describe_with_combat(ev.describe, challenger_id, defender_id, stacks),
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
        speaker="neutral",
    )
    narr.add(f"第{round_index}幕·{TAG_EXCHANGE} {ev.event_id}")
    victim = primary_hp_loss_side(snap, stacks)
    run_qte = bool(ev.qte)
    if not run_qte and victim and random.random() < plugin_config.duel_exchange_qte_chance:
        run_qte = True
    if run_qte:
        qte_ev = ev
        qte_actor = victim or "challenger"
        if not qte_ev.qte:
            qte_ev = LoadedEvent(
                event_id=ev.event_id,
                weight=ev.weight,
                describe=ev.describe,
                effects=[],
                qte=build_exchange_auto_qte(qte_actor),
            )
        else:
            qte_actor = qte_actor_from_target(qte_ev.qte, qte_actor)
        await run_event_qte_if_any(
            matcher,
            group_id,
            challenger_id,
            defender_id,
            stacks,
            qte_ev,
            qte_actor,
            narr_log=narr,
            round_index=round_index,
            round_tag=TAG_EXCHANGE,
            bot_mode=bot_mode,
            challenger_is_bot=challenger_is_bot,
            defender_is_bot=defender_is_bot,
        )
    return exchange_changed_hp_dp


def _is_operator_intrusion(ev: LoadedEvent | None) -> bool:
    return bool(ev and ev.qte and ev.qte.get("type") == "operator_intrusion")


def pick_public_round_event(public_pool: list[LoadedEvent]) -> LoadedEvent | None:
    """歌咏场：先按配置掷乱入概率，否则在泰拉公共池中加权抽取。"""
    if not public_pool:
        return None
    intrusion = [e for e in public_pool if _is_operator_intrusion(e)]
    terra = [e for e in public_pool if not _is_operator_intrusion(e)]
    if intrusion and random.random() < plugin_config.duel_operator_intrusion_chance:
        return _pick_weighted(intrusion)
    if terra:
        return _pick_weighted(
            terra,
            qte_mult=plugin_config.duel_qte_event_weight_mult,
            weight_mult=plugin_config.duel_public_terra_weight_mult,
        )
    return _pick_weighted(intrusion)


async def _play_clash_side(
    matcher: Matcher,
    group_id: int,
    challenger_id: str,
    defender_id: str,
    stacks: DuelStacks,
    ev: LoadedEvent | None,
    actor: Actor,
    narr: DuelNarrativeLog,
    round_index: int,
    *,
    bot_mode: bool,
    challenger_is_bot: bool,
    defender_is_bot: bool,
    intrusion_tag: str,
    qte_tag: str,
    silent_line: str,
    narr_key: str,
    skip_describe: bool = False,
) -> None:
    """单攻或单守台词（双牛分号、乱入专场）。"""
    from src.plugins.duel.duel_qte import run_event_qte_if_any
    from src.plugins.duel.duel_send import send_duel_line

    speaker = "challenger" if actor == "challenger" else "defender"
    if not ev:
        if not skip_describe:
            await send_duel_line(
                group_id,
                silent_line,
                matcher=matcher,
                challenger_id=challenger_id,
                defender_id=defender_id,
                bot_mode=bot_mode,
                challenger_is_bot=challenger_is_bot,
                defender_is_bot=defender_is_bot,
                speaker=speaker,
            )
        return
    ark = _maybe_pick_ark_ctx(ev)
    if _is_operator_intrusion(ev):
        await run_event_qte_if_any(
            matcher,
            group_id,
            challenger_id,
            defender_id,
            stacks,
            ev,
            actor,
            intrusion_ctx=ark,
            scene_card=ev.describe,
            narr_log=narr,
            round_index=round_index,
            round_tag=intrusion_tag,
            bot_mode=bot_mode,
            challenger_is_bot=challenger_is_bot,
            defender_is_bot=defender_is_bot,
        )
        return
    snap = snapshot_combat(stacks)
    apply_event_effects(stacks, ev, actor)
    if not skip_describe:
        await send_duel_line(
            group_id,
            append_combat_delta(
                format_describe_with_combat(ev.describe, challenger_id, defender_id, stacks, ark),
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
            speaker=speaker,
        )
    narr.add(f"第{round_index}幕·{narr_key} {ev.event_id}")
    await run_event_qte_if_any(
        matcher,
        group_id,
        challenger_id,
        defender_id,
        stacks,
        ev,
        actor,
        intrusion_ctx=ark,
        narr_log=narr,
        round_index=round_index,
        round_tag=qte_tag,
        bot_mode=bot_mode,
        challenger_is_bot=challenger_is_bot,
        defender_is_bot=defender_is_bot,
    )


async def play_clash_hero_events(
    matcher: Matcher,
    group_id: int,
    challenger_id: str,
    defender_id: str,
    stacks: DuelStacks,
    pools: dict[PoolName, list[LoadedEvent]],
    narr: DuelNarrativeLog,
    round_index: int,
    *,
    bot_mode: bool,
    challenger_is_bot: bool,
    defender_is_bot: bool,
    skip_describe: bool = False,
) -> None:
    """交锋攻守：人类局合并一段台词，双牛仍分开发。"""
    from src.plugins.duel.duel_qte import run_event_qte_if_any
    from src.plugins.duel.duel_send import send_duel_line

    ce = _pick_weighted(pools["challenger"], qte_mult=plugin_config.duel_qte_event_weight_mult)
    de = _pick_weighted(pools["defender"], qte_mult=plugin_config.duel_qte_event_weight_mult)

    if not bot_mode and not _is_operator_intrusion(ce) and not _is_operator_intrusion(de):
        ark_c: dict[str, str] | None = None
        ark_d: dict[str, str] | None = None
        if skip_describe:
            if ce:
                ark_c = _maybe_pick_ark_ctx(ce)
                apply_event_effects(stacks, ce, "challenger")
                narr.add(f"第{round_index}幕·{TAG_CLASH_ATTACK} {ce.event_id}")
            if de:
                ark_d = _maybe_pick_ark_ctx(de)
                apply_event_effects(stacks, de, "defender")
                narr.add(f"第{round_index}幕·{TAG_CLASH_DEFEND} {de.event_id}")
        else:
            chunks: list[Message] = []
            if ce:
                ark_c = _maybe_pick_ark_ctx(ce)
                snap = snapshot_combat(stacks)
                apply_event_effects(stacks, ce, "challenger")
                chunks.append(
                    append_combat_delta(
                        format_describe_with_combat(ce.describe, challenger_id, defender_id, stacks, ark_c),
                        challenger_id,
                        defender_id,
                        snap,
                        stacks,
                    )
                )
                narr.add(f"第{round_index}幕·{TAG_CLASH_ATTACK} {ce.event_id}")
            else:
                chunks.append(duel_plain(CLASH_SILENT_ATTACKER))
            if de:
                ark_d = _maybe_pick_ark_ctx(de)
                snap = snapshot_combat(stacks)
                apply_event_effects(stacks, de, "defender")
                chunks.append(
                    append_combat_delta(
                        format_describe_with_combat(de.describe, challenger_id, defender_id, stacks, ark_d),
                        challenger_id,
                        defender_id,
                        snap,
                        stacks,
                    )
                )
                narr.add(f"第{round_index}幕·{TAG_CLASH_DEFEND} {de.event_id}")
            else:
                chunks.append(duel_plain(CLASH_SILENT_DEFENDER))
            await send_duel_line(
                group_id,
                duel_join_blocks(chunks, sep="\n\n"),
                matcher=matcher,
                challenger_id=challenger_id,
                defender_id=defender_id,
                bot_mode=False,
                challenger_is_bot=challenger_is_bot,
                defender_is_bot=defender_is_bot,
                speaker="neutral",
            )
        if ce and ce.qte:
            await run_event_qte_if_any(
                matcher,
                group_id,
                challenger_id,
                defender_id,
                stacks,
                ce,
                "challenger",
                intrusion_ctx=ark_c,
                narr_log=narr,
                round_index=round_index,
                round_tag=TAG_CLASH_ATTACK,
                bot_mode=False,
                challenger_is_bot=challenger_is_bot,
                defender_is_bot=defender_is_bot,
            )
        if de and de.qte:
            await run_event_qte_if_any(
                matcher,
                group_id,
                challenger_id,
                defender_id,
                stacks,
                de,
                "defender",
                intrusion_ctx=ark_d,
                narr_log=narr,
                round_index=round_index,
                round_tag=TAG_CLASH_DEFEND,
                bot_mode=False,
                challenger_is_bot=challenger_is_bot,
                defender_is_bot=defender_is_bot,
            )
        return

    await _play_clash_side(
        matcher,
        group_id,
        challenger_id,
        defender_id,
        stacks,
        ce,
        "challenger",
        narr,
        round_index,
        bot_mode=bot_mode,
        challenger_is_bot=challenger_is_bot,
        defender_is_bot=defender_is_bot,
        intrusion_tag=TAG_CLASH_INTRUSION_ATTACK,
        qte_tag=TAG_CLASH_ATTACK,
        silent_line=CLASH_SILENT_ATTACKER,
        narr_key=TAG_CLASH_ATTACK,
        skip_describe=skip_describe,
    )
    await _play_clash_side(
        matcher,
        group_id,
        challenger_id,
        defender_id,
        stacks,
        de,
        "defender",
        narr,
        round_index,
        bot_mode=bot_mode,
        challenger_is_bot=challenger_is_bot,
        defender_is_bot=defender_is_bot,
        intrusion_tag=TAG_CLASH_INTRUSION_DEFEND,
        qte_tag=TAG_CLASH_DEFEND,
        silent_line=CLASH_SILENT_DEFENDER,
        narr_key=TAG_CLASH_DEFEND,
        skip_describe=skip_describe,
    )


async def pause_between_duel_rounds(round_index: int, pause_lo: float, pause_hi: float) -> None:
    """幕间停顿；第 1 幕前不等待（开演说明后立刻进入第一幕）。"""
    if round_index <= 1:
        return
    if pause_lo <= 0 and pause_hi <= 0:
        return
    await asyncio.sleep(random.uniform(pause_lo, pause_hi))


async def play_duel_rounds(
    matcher: Matcher,
    bot: Bot,
    group_id: int,
    challenger_id: str,
    defender_id: str,
    *,
    bot_mode: bool = False,
    challenger_is_bot: bool = False,
    defender_is_bot: bool = False,
    round_pause_sec: tuple[float, float] | None = None,
    total_rounds: int | None = None,
) -> DuelStacks | None:
    """主流程：开演说明 → 若干幕 → 终幕。干员乱入事件的顶层 effects 不生效，请写在 qte 的 on_*_effects。"""
    from src.plugins.duel.duel_qte import run_event_qte_if_any
    from src.plugins.duel.duel_send import (
        begin_round_line_buffer,
        bind_duel_routing_bot,
        flush_round_line_buffer,
        reset_duel_routing_bot,
        reset_round_line_buffer,
        send_duel_line,
    )

    pools = get_event_pools()
    if not pools["challenger"] or not pools["defender"]:
        logger.error("duel challenger/defender event pool empty")
        return None
    if not pools["public"]:
        logger.warning("duel public pool empty, public rounds will skip")

    routing_token = bind_duel_routing_bot(bot)
    labels = await resolve_duel_labels(bot, group_id, challenger_id, defender_id)
    labels_token = bind_duel_labels(labels)

    stacks = DuelStacks()
    rounds = total_rounds if total_rounds is not None else plugin_config.duel_total_rounds
    plan = run_round_plan(rounds)
    narr = DuelNarrativeLog()
    try:
        opener = (
            duel_text("擂台灯光压暗。")
            + duel_at(challenger_id)
            + duel_text(" 与 ")
            + duel_at(defender_id)
            + duel_text(" 步入场心，对决开始。")
        )
        if bot_mode:
            opener = append_duel_message(duel_plain("不需畏惧，我会战胜那个鲁莽的家伙！"), opener)
        await send_duel_line(
            group_id,
            opener,
            matcher=matcher,
            challenger_id=challenger_id,
            defender_id=defender_id,
            bot_mode=bot_mode,
            challenger_is_bot=challenger_is_bot,
            defender_is_bot=defender_is_bot,
            speaker="neutral",
        )

        pause_lo, pause_hi = round_pause_sec or (
            plugin_config.duel_round_pause_min_sec,
            plugin_config.duel_round_pause_max_sec,
        )

        for i, kind in enumerate(plan, start=1):
            if stacks.is_ko():
                break
            await pause_between_duel_rounds(i, pause_lo, pause_hi)
            round_buf_token = begin_round_line_buffer(
                group_id=group_id,
                matcher=matcher,
                challenger_id=challenger_id,
                defender_id=defender_id,
                bot_mode=bot_mode,
                challenger_is_bot=challenger_is_bot,
                defender_is_bot=defender_is_bot,
                speaker="neutral",
            )
            try:
                round_start = snapshot_combat(stacks)
                hdr = f"第{i}/{rounds}幕 · "
                if kind == "public":
                    hdr += ROUND_KIND_PUBLIC
                    ev = pick_public_round_event(pools["public"])
                    if ev:
                        ark = _maybe_pick_ark_ctx(ev)
                        is_intrusion = bool(ev.qte and ev.qte.get("type") == "operator_intrusion")
                        if is_intrusion:
                            await run_event_qte_if_any(
                                matcher,
                                group_id,
                                challenger_id,
                                defender_id,
                                stacks,
                                ev,
                                "challenger",
                                intrusion_ctx=ark,
                                round_header=hdr,
                                scene_card=ev.describe,
                                narr_log=narr,
                                round_index=i,
                                round_tag=TAG_PUBLIC_INTRUSION,
                                bot_mode=bot_mode,
                                challenger_is_bot=challenger_is_bot,
                                defender_is_bot=defender_is_bot,
                            )
                        else:
                            snap = snapshot_combat(stacks)
                            apply_event_effects(stacks, ev, "challenger")
                            line = append_combat_delta(
                                duel_join_lines(
                                    hdr,
                                    format_describe_with_combat(ev.describe, challenger_id, defender_id, stacks, ark),
                                ),
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
                            )
                            narr.add(f"第{i}幕·{TAG_PUBLIC} {ev.event_id}")
                            await run_event_qte_if_any(
                                matcher,
                                group_id,
                                challenger_id,
                                defender_id,
                                stacks,
                                ev,
                                "challenger",
                                intrusion_ctx=ark,
                                narr_log=narr,
                                round_index=i,
                                round_tag=TAG_PUBLIC,
                                bot_mode=bot_mode,
                                challenger_is_bot=challenger_is_bot,
                                defender_is_bot=defender_is_bot,
                            )
                    else:
                        await send_duel_line(
                            group_id,
                            hdr + f"\n{PUBLIC_ROUND_EMPTY}",
                            matcher=matcher,
                            challenger_id=challenger_id,
                            defender_id=defender_id,
                            bot_mode=bot_mode,
                            challenger_is_bot=challenger_is_bot,
                            defender_is_bot=defender_is_bot,
                        )
                else:
                    hdr += ROUND_KIND_CLASH
                    from src.plugins.duel.duel_send import round_buffer_prepend, send_duel_line

                    if plugin_config.duel_compact_round:
                        round_buffer_prepend(hdr)
                    else:
                        await send_duel_line(
                            group_id,
                            hdr,
                            matcher=matcher,
                            challenger_id=challenger_id,
                            defender_id=defender_id,
                            bot_mode=bot_mode,
                            challenger_is_bot=challenger_is_bot,
                            defender_is_bot=defender_is_bot,
                        )
                    exchange_changed_hp_dp = False
                    if pools["exchange"]:
                        exchange_changed_hp_dp = await run_exchange_bout(
                            matcher,
                            group_id,
                            challenger_id,
                            defender_id,
                            stacks,
                            pools["exchange"],
                            narr,
                            i,
                            bot_mode=bot_mode,
                            challenger_is_bot=challenger_is_bot,
                            defender_is_bot=defender_is_bot,
                        )
                    await play_clash_hero_events(
                        matcher,
                        group_id,
                        challenger_id,
                        defender_id,
                        stacks,
                        pools,
                        narr,
                        i,
                        bot_mode=bot_mode,
                        challenger_is_bot=challenger_is_bot,
                        defender_is_bot=defender_is_bot,
                        skip_describe=exchange_changed_hp_dp,
                    )
                round_snap = round_start if plugin_config.duel_compact_round else None
                await flush_round_line_buffer(
                    format_round_status_line(
                        challenger_id,
                        defender_id,
                        stacks,
                        round_start=round_snap,
                    )
                )
            finally:
                reset_round_line_buffer(round_buf_token)
            if stacks.is_ko():
                break

        await asyncio.sleep(random.uniform(pause_lo, pause_hi))
        await send_duel_line(
            group_id,
            summarize_winner(challenger_id, defender_id, stacks, total_rounds=rounds, ko=stacks.is_ko()),
            matcher=matcher,
            challenger_id=challenger_id,
            defender_id=defender_id,
            bot_mode=bot_mode,
            challenger_is_bot=challenger_is_bot,
            defender_is_bot=defender_is_bot,
            speaker="neutral",
        )
    finally:
        reset_duel_labels(labels_token)
        reset_duel_routing_bot(routing_token)
    return stacks
