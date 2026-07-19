"""Repeater LLM 统一塑形：system prompt + rewrite 元数据。"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from pallas.core.foundation.db import make_group_config_repository
from pallas.product.llm.dynamic_expression_context import build_dynamic_expression_hint
from pallas.product.llm.inference_params import derive_llm_inference_params
from pallas.product.llm.persona_context import build_persona_llm_context
from pallas.product.llm.reply_variation import (
    build_variation_hint_from_recent_texts,
    classify_repeated_opener,
)
from pallas.product.persona import resolve_persona_for_message
from pallas.product.persona.affect_kernel import (
    build_persona_affect_contract,
    build_repeater_persona_affect_system_block,
    build_variation_hint_from_contract,
    group_flavor_summary_from_style_snapshot,
)
from pallas.product.persona.compile_group_style import compile_group_style_snapshot
from pallas.product.persona.compile_persona_prompt import (
    load_fallback_lite_system_prompt,
    load_polish_lite_system_prompt,
    resolve_select_system_prompt_path,
)

_STATIC_BASE_LOADERS = {
    "polish_lite": load_polish_lite_system_prompt,
    "fallback_lite": load_fallback_lite_system_prompt,
}


@dataclass(frozen=True, slots=True)
class RepeaterLlmPersonaBundle:
    system_prompt: str
    temperature: float | None
    token_count: int | None
    llm_rewrite_metadata: dict[str, Any]
    affect_block: str = ""
    variation_hint: str = ""
    dynamic_expression_hint: str = ""


async def load_recent_bot_plain_replies(bot_id: int, group_id: int, *, limit: int = 6) -> list[str]:
    from pallas.core.foundation.db import make_message_repository

    repo = make_message_repository()
    try:
        messages = await repo.find_recent_in_group(int(group_id), before_time=int(time.time()) + 1, limit=48)
    except Exception:
        return []

    bids = int(bot_id)
    out: list[str] = []
    for msg in messages:
        uid = int(getattr(msg, "user_id", 0) or 0)
        bmid = int(getattr(msg, "bot_id", 0) or 0)
        if uid != bids and bmid != bids:
            continue
        plain = str(getattr(msg, "plain_text", "") or "").strip()
        if not plain or "[CQ:" in plain:
            continue
        out.append(plain)
        if len(out) >= max(1, int(limit)):
            break
    return out


def _load_select_system_prompt() -> str:
    path = resolve_select_system_prompt_path()
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()
    return ""


async def resolve_repeater_base_system(
    bot_id: int,
    group_id: int,
    plain_text: str,
    *,
    purpose: str,
    mode: str = "normal",
) -> tuple[str, float | None, int | None]:
    normalized_purpose = str(purpose or "").strip().lower()
    persona = await resolve_persona_for_message(bot_id, group_id, plain_text)
    temperature, token_count = derive_llm_inference_params(persona, mode=mode, purpose=normalized_purpose)

    if normalized_purpose == "select":
        base = _load_select_system_prompt()
        if base:
            return base, temperature, token_count

    static_loader = _STATIC_BASE_LOADERS.get(normalized_purpose)
    if static_loader is not None:
        base = str(static_loader() or "").strip()
        if base:
            return base, temperature, token_count

    bundle, temperature, token_count = await build_persona_llm_context(
        bot_id,
        group_id,
        plain_text,
        mode=mode,
        purpose=normalized_purpose or "fallback",
    )
    return bundle.system.strip(), temperature, token_count


async def build_repeater_llm_persona_context(
    bot_id: int,
    group_id: int,
    plain_text: str,
    *,
    purpose: str,
    mode: str = "normal",
    user_id: int | None = None,
    feedback_suffix: str = "",
) -> RepeaterLlmPersonaBundle | None:
    plain = str(plain_text or "").strip()
    if not plain:
        return None

    base_system, temperature, token_count = await resolve_repeater_base_system(
        bot_id,
        group_id,
        plain,
        purpose=purpose,
        mode=mode,
    )
    if not base_system:
        return None

    persona = await resolve_persona_for_message(bot_id, group_id, plain)
    group_style: dict[str, Any] | None = None
    try:
        group_config = await make_group_config_repository().get(int(group_id))
    except Exception:
        group_config = None
    raw_profile = getattr(group_config, "style_profile", None) if group_config is not None else None
    if isinstance(raw_profile, dict):
        group_style = raw_profile

    recent_replies = await load_recent_bot_plain_replies(bot_id, group_id)
    openers: list[str] = []
    for text in reversed(recent_replies):
        opener = classify_repeated_opener(text)
        if opener and opener not in openers:
            openers.append(opener)
        if len(openers) >= 3:
            break

    from pallas.product.llm.kernel.models import normalize_conversation_mode

    group_flavor = group_flavor_summary_from_style_snapshot(compile_group_style_snapshot(group_style))
    affect_contract = build_persona_affect_contract(
        persona,
        mode=normalize_conversation_mode(str(mode or "normal")),
        group_flavor_summary=group_flavor,
        repeated_openers=openers,
    )
    affect_block = build_repeater_persona_affect_system_block(affect_contract)
    dynamic_expression_hint = await build_dynamic_expression_hint(
        group_id,
        plain,
        bot_id=bot_id,
        current_user_id=user_id,
    )
    variation_hint = build_variation_hint_from_recent_texts(recent_replies)
    contract_variation = build_variation_hint_from_contract(affect_contract)
    if contract_variation and contract_variation not in variation_hint:
        variation_hint = f"{variation_hint}\n{contract_variation}".strip() if variation_hint else contract_variation

    parts = [base_system.rstrip()]
    if affect_block:
        parts.append(affect_block)
    if dynamic_expression_hint:
        parts.append(dynamic_expression_hint.strip())
    if variation_hint:
        parts.append(variation_hint.strip())
    feedback = str(feedback_suffix or "").strip()
    if feedback:
        parts.append(feedback)

    shaping_active = bool(affect_block or dynamic_expression_hint or variation_hint)
    llm_rewrite_metadata = {
        "persona_affect_block": affect_block,
        "dynamic_expression_hint": dynamic_expression_hint,
        "variation_hint": variation_hint,
        "persona_shaping_active": shaping_active,
        "persona_shaping_profile": "repeater",
        "preserve_colloquial_rewrite": shaping_active,
    }

    return RepeaterLlmPersonaBundle(
        system_prompt="\n\n".join(part for part in parts if part),
        temperature=temperature,
        token_count=token_count,
        llm_rewrite_metadata=llm_rewrite_metadata,
        affect_block=affect_block,
        variation_hint=variation_hint,
        dynamic_expression_hint=dynamic_expression_hint,
    )
