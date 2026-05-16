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

from src.plugins.block import plugin_config as block_plugin_config
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
    QTE_FAIL_TAIL,
    QTE_INTRUSION_FAIL_STUB,
    QTE_INTRUSION_TITLE,
    QTE_KEYWORD_TITLE,
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
    if int(responder) not in block_plugin_config.bots:
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

    asyncio.create_task(job())


async def duel_qte_message_rule(bot: Bot, event: Event) -> bool:
    """仅当存在未过期且未完成的 QTE 会话、且文本与要求完全一致时放行。"""
    if not isinstance(event, GroupMessageEvent):
        return False
    sid = qte_session_id(event.group_id, event.get_user_id())
    sess = _sessions.get(sid)
    if sess is None or sess.future.done():
        return False
    if time.time() > sess.deadline:
        return False
    return event.get_plaintext().strip() == sess.required_key


duel_qte_exact_rule = Rule(duel_qte_message_rule)


def complete_duel_qte(event: GroupMessageEvent) -> None:
    """将当前群的 QTE 标记为成功。"""
    sid = qte_session_id(event.group_id, event.get_user_id())
    sess = _sessions.get(sid)
    if sess is None or sess.future.done():
        return
    sess.future.set_result(True)


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
    schedule_bot_qte_auto_answer(group_id, responder, required_key, fut, window_sec, qte_kind="intrusion")
    ok = False
    try:
        ok = await asyncio.wait_for(fut, timeout=window_sec + 1.0)
    except TimeoutError:
        ok = False
    finally:
        _sessions.pop(sid, None)

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
    """若事件带 QTE：乱入走专场（round_header/scene_card 拼首条），否则关键词 QTE。"""
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
    for sid, sess in list(_sessions.items()):
        if not sess.future.done():
            sess.future.set_result(False)
            n += 1
        _sessions.pop(sid, None)
    return n
