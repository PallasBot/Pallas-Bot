"""接话命中语料时 LLM 情绪选句，默认推荐（替代 polish）。"""

from __future__ import annotations

import re
import time
from operator import itemgetter
from typing import TYPE_CHECKING

from nonebot import logger
from ulid import ULID

from pallas.core.foundation.config import TaskManager
from pallas.core.platform.ai_callback.task_types import REPEATER_SELECT_TASK_TYPE
from pallas.product.llm.client import submit_chat_task
from pallas.product.llm.config import get_llm_config
from pallas.product.llm.models import ChatSubmitRequest
from pallas.product.llm.repeater_persona_context import build_repeater_llm_persona_context
from pallas.product.llm.task_metrics import record_bot_llm_task
from pallas.product.persona.compile_persona_prompt import resolve_select_system_prompt_path

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import GroupMessageEvent

_SELECT_INDEX_RE = re.compile(r"(\d+)")


def load_select_system_prompt() -> str:
    path = resolve_select_system_prompt_path()
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()
    return ""


def filter_select_candidate_pool(candidates: list[str]) -> tuple[list[str], dict[str, int]]:
    from pallas.product.llm.corpus_contamination import is_corpus_learn_safe, is_llm_learning_safe

    raw_count = len(candidates)
    skipped_contamination = 0
    safe: list[str] = []
    for text in candidates:
        sample = str(text or "").strip()
        if not sample or "[CQ:" in sample:
            continue
        if not is_llm_learning_safe(sample) or not is_corpus_learn_safe(sample):
            skipped_contamination += 1
            continue
        safe.append(sample)
    return safe, {
        "raw_count": raw_count,
        "safe_count": len(safe),
        "skipped_contamination": skipped_contamination,
    }


def build_select_pool_diag(
    *,
    raw_pool: list[str],
    safe_pool: list[str],
    ranked: list[str],
    skip_reason: str = "",
) -> dict[str, int | str]:
    return {
        "raw_count": len(raw_pool),
        "safe_count": len(safe_pool),
        "ranked_count": len(ranked),
        "skipped_contamination": max(0, len(raw_pool) - len(safe_pool)),
        "skip_reason": str(skip_reason or ""),
    }


async def rank_select_candidates(
    bot_id: int,
    group_id: int,
    plain_text: str,
    candidates: list[str],
    *,
    limit: int,
) -> list[str]:
    from pallas.product.persona import resolve_persona_for_message
    from pallas.product.persona.loader import load_affect_triggers
    from pallas.product.persona.scorer import message_weight_multiplier

    persona = await resolve_persona_for_message(bot_id, group_id, plain_text)
    affect_triggers = await load_affect_triggers(group_id)
    from pallas.product.llm.corpus_contamination import is_corpus_learn_safe

    scored: list[tuple[float, str]] = []
    for text in candidates:
        sample = str(text or "").strip()
        if not sample or "[CQ:" in sample:
            continue
        if not is_corpus_learn_safe(sample):
            continue
        weight = message_weight_multiplier(sample, persona, affect_triggers=affect_triggers)
        scored.append((weight, sample))
    scored.sort(key=itemgetter(0), reverse=True)
    seen: set[str] = set()
    ranked: list[str] = []
    for _, sample in scored:
        if sample in seen:
            continue
        seen.add(sample)
        ranked.append(sample)
        if len(ranked) >= max(1, int(limit)):
            break
    return ranked


async def build_select_context_hints(bot_id: int, group_id: int, plain_text: str) -> str:
    from pallas.core.foundation.db import make_group_config_repository
    from pallas.product.persona.compile_group_style import compile_group_style_snapshot
    from pallas.product.persona.loader import load_affect_triggers

    group_config = await make_group_config_repository().get(int(group_id))
    profile = getattr(group_config, "style_profile", None) if group_config is not None else None
    snapshot = compile_group_style_snapshot(profile if isinstance(profile, dict) else None)
    parts: list[str] = []
    if snapshot.get("ready"):
        hints = snapshot.get("hints") or []
        if hints:
            parts.append("群习惯：" + "、".join(str(item) for item in hints[:3]))
        signals = snapshot.get("signals") or {}
        length_pref = str(signals.get("length_pref") or "").strip()
        if length_pref and length_pref != "any":
            parts.append(f"句长偏好：{length_pref}")
    triggers = await load_affect_triggers(group_id)
    plain_lower = plain_text.strip().lower()
    matched = [
        str(item.get("phrase") or "").strip()
        for item in triggers
        if str(item.get("phrase") or "").strip() and str(item.get("phrase") or "").strip() in plain_lower
    ]
    matched = [item for item in matched if item][:4]
    if matched:
        parts.append("语境触发：" + "、".join(matched))
    _ = bot_id
    return "；".join(parts)


def build_select_user_text(
    user_text: str,
    candidates: list[str],
    *,
    context_hints: str = "",
) -> str:
    message = str(user_text or "").strip()
    pool = [str(item).strip() for item in candidates if str(item).strip()]
    if not message or not pool:
        return ""
    lines = [
        f"【用户消息】{message}",
    ]
    hints = str(context_hints or "").strip()
    if hints:
        lines.append(f"【语境参考】{hints}")
    lines.append("【候选回复】")
    lines.extend(f"{index}. {text}" for index, text in enumerate(pool, start=1))
    lines.append("请根据当前语境与情绪选出最合适的一条编号；都不合适则输出 0。")
    return "\n".join(lines)


def parse_select_response(raw: str, candidates: list[str]) -> str | None:
    text = str(raw or "").strip()
    if not text:
        return None
    if text == "0":
        return None
    pool = [str(item).strip() for item in candidates if str(item).strip()]
    if not pool:
        return None
    match = _SELECT_INDEX_RE.search(text)
    if match:
        index = int(match.group(1)) - 1
        if 0 <= index < len(pool):
            return pool[index]
    for sample in pool:
        if sample == text or text in sample:
            return sample
    return None


def resolve_select_callback_text(raw: str, candidates: list[str], fallback_text: str) -> str:
    selected = parse_select_response(raw, candidates)
    if selected:
        return selected
    fallback = str(fallback_text or "").strip()
    from pallas.product.llm.corpus_contamination import is_llm_learning_safe

    return fallback if is_llm_learning_safe(fallback) else ""


async def maybe_submit_repeater_llm_select(
    event: GroupMessageEvent,
    *,
    user_text: str,
    candidates: list[str],
    fallback_text: str,
    source: str = "repeater",
    reply_mode: str = "normal",
) -> bool:
    cfg = get_llm_config()
    if not cfg.llm_select_enabled or not cfg.llm_chat_enabled:
        return False

    plain = str(user_text or "").strip()
    if not plain or "[CQ:" in plain:
        return False

    group_id = int(event.group_id)
    user_id = int(event.user_id)
    bot_id = int(event.self_id)

    raw_pool = [str(item).strip() for item in candidates if str(item).strip() and "[CQ:" not in str(item)]
    safe_pool, _filter_diag = filter_select_candidate_pool(raw_pool)
    if len(safe_pool) < 2:
        from pallas.product.llm.runtime_debug import append_select_pool_observation

        diag = build_select_pool_diag(
            raw_pool=raw_pool,
            safe_pool=safe_pool,
            ranked=[],
            skip_reason="safe_pool_too_small",
        )
        append_select_pool_observation(
            bot_id=bot_id,
            group_id=group_id,
            user_id=user_id,
            source=source,
            diag=diag,
        )
        record_bot_llm_task(REPEATER_SELECT_TASK_TYPE, "submit_skip")
        logger.debug(
            "repeater llm select skipped: safe_pool={} raw={} contamination_skipped={} source={}",
            len(safe_pool),
            len(raw_pool),
            diag.get("skipped_contamination"),
            source,
        )
        return False

    ranked = await rank_select_candidates(
        bot_id,
        group_id,
        plain,
        safe_pool,
        limit=cfg.llm_select_max_candidates,
    )
    if len(ranked) < 2:
        from pallas.product.llm.runtime_debug import append_select_pool_observation

        diag = build_select_pool_diag(
            raw_pool=raw_pool,
            safe_pool=safe_pool,
            ranked=ranked,
            skip_reason="ranked_pool_too_small",
        )
        append_select_pool_observation(
            bot_id=bot_id,
            group_id=group_id,
            user_id=user_id,
            source=source,
            diag=diag,
        )
        record_bot_llm_task(REPEATER_SELECT_TASK_TYPE, "submit_skip")
        logger.debug(
            "repeater llm select skipped: ranked={} safe={} source={}",
            len(ranked),
            len(safe_pool),
            source,
        )
        return False

    fallback = str(fallback_text or "").strip()
    from pallas.product.llm.corpus_contamination import is_llm_learning_safe

    if not is_llm_learning_safe(fallback):
        fallback = ranked[0]
    hints = await build_select_context_hints(bot_id, group_id, plain)
    prompt_user = build_select_user_text(plain, ranked, context_hints=hints)
    if not prompt_user:
        return False

    from pallas.product.llm.feedback_chat_hint import load_repeater_feedback_system_suffix

    feedback_hint = await load_repeater_feedback_system_suffix(group_id=group_id, user_text=plain)
    persona_bundle = await build_repeater_llm_persona_context(
        bot_id,
        group_id,
        plain,
        purpose="select",
        mode=str(reply_mode or "normal"),
        user_id=user_id,
        feedback_suffix=feedback_hint,
    )
    if persona_bundle is None or not persona_bundle.system_prompt:
        return False

    pool_diag = build_select_pool_diag(raw_pool=raw_pool, safe_pool=safe_pool, ranked=ranked)
    rewrite_metadata = dict(persona_bundle.llm_rewrite_metadata)
    rewrite_metadata["select_pool_diag"] = pool_diag

    session_id = f"repeater_sl_{bot_id}_{group_id}_{user_id}"
    request_id = str(ULID())
    await TaskManager.add_task(
        request_id,
        {
            "bot_id": bot_id,
            "group_id": group_id,
            "user_id": user_id,
            "task_type": REPEATER_SELECT_TASK_TYPE,
            "user_text": plain,
            "fallback_text": fallback,
            "candidate_pool": list(ranked),
            "select_source": source,
            "reply_mode": str(reply_mode or "normal"),
            "start_time": time.time(),
        },
    )
    result = await submit_chat_task(
        ChatSubmitRequest(
            request_id=request_id,
            session_id=session_id,
            user_text=prompt_user,
            system_prompt=persona_bundle.system_prompt,
            bot_id=bot_id,
            group_id=group_id,
            user_id=user_id,
            mode="normal",
            task="repeater_select",
            token_count=persona_bundle.token_count,
            temperature=persona_bundle.temperature,
            llm_rewrite_metadata=rewrite_metadata,
        ),
        cfg=cfg,
    )
    if not result.ok:
        await TaskManager.remove_task(request_id)
        record_bot_llm_task(REPEATER_SELECT_TASK_TYPE, "submit_skip")
        logger.debug(
            "repeater llm select submit skipped: status={} group={} user={} source={}",
            result.status,
            group_id,
            user_id,
            source,
        )
        return False

    record_bot_llm_task(REPEATER_SELECT_TASK_TYPE, "submit_ok")
    logger.info(
        "repeater llm select queued: request_id={} group={} user={} candidates={} source={}",
        request_id,
        group_id,
        user_id,
        len(ranked),
        source,
    )
    return True
