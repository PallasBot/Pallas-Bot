"""Shared persona-affect authority for repeater and llm_chat."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from pallas.product.llm.kernel.models import ConversationMode, DecisionConstraints

if TYPE_CHECKING:
    from pallas.product.persona.model import ResolvedPersona


class PersonaAffectContract(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    stance_hints: list[str] = Field(default_factory=list)
    disallowed_tones: list[str] = Field(default_factory=list)
    preferred_length_min: int = Field(default=1, ge=0)
    preferred_length_max: int = Field(default=36, ge=0)
    opener_suppression_hints: list[str] = Field(default_factory=list)
    ending_constraints: list[str] = Field(default_factory=list)
    mode_tolerance: float = Field(default=1.0, ge=0.0, le=2.0)


def build_persona_affect_contract(
    persona: ResolvedPersona | None = None,
    *,
    mode: ConversationMode = ConversationMode.NORMAL,
    group_flavor_summary: str = "",
    repeated_openers: list[str] | None = None,
) -> PersonaAffectContract:
    length_pref = str(getattr(persona, "length_pref", "") or "").strip().lower() if persona else ""
    if length_pref == "short":
        preferred_min, preferred_max = 1, 16
    elif length_pref == "long":
        preferred_min, preferred_max = 8, 64
    else:
        preferred_min, preferred_max = 1, 36

    if mode == ConversationMode.GHOST:
        preferred_max = min(preferred_max, 12)
    elif mode == ConversationMode.GOD:
        preferred_min = max(preferred_min, 2)
        preferred_max = min(preferred_max, 48)

    disallowed = ["客服腔", "教学腔", "总结腔"]
    stance_hints: list[str] = []
    if group_flavor_summary:
        stance_hints.append(group_flavor_summary)

    if length_pref == "short":
        stance_hints.append("优先 1-2 句短口语，像顺手回一句，别展开解释。")
    elif length_pref == "long":
        stance_hints.append("可稍多说一两句，但仍要像群聊接话，别写小作文。")
    else:
        stance_hints.append("像被 @ 后顺口接话，2 句内为主，别写成完整答复。")

    if persona is not None:
        warmth = float(getattr(persona, "warmth", 0.0) or 0.0)
        chaos = float(getattr(persona, "chaos_bias", 0.0) or 0.0)
        assertiveness = float(getattr(persona, "assertiveness", 0.0) or 0.0)
        if warmth >= 0.1:
            stance_hints.append("语气可稍软、更接梗，但别像哄人或客服安抚。")
        elif warmth <= -0.1:
            stance_hints.append("语气偏克制，少热情铺垫，直接接重点。")
        if chaos >= 0.5:
            stance_hints.append("可更跳脱接梗，但别硬拗、别演过头。")
        elif chaos >= 0.12:
            stance_hints.append("本群偏短句接梗，可更跳、更口语，但仍别哞~/颜文字起手。")
        if assertiveness >= 0.1:
            stance_hints.append("可适度反抛或顶一句，像群友接梗即可。")
        elif assertiveness <= -0.1:
            stance_hints.append("少反呛，顺着话题接，别抢戏。")

    opener_hints = [item for item in list(repeated_openers or []) if item]
    ending_constraints = ["避免固定模板收口", "避免连续重复同一开头"]
    mode_tolerance = 1.0
    if mode == ConversationMode.GHOST:
        mode_tolerance = 0.85
    elif mode == ConversationMode.GOD:
        mode_tolerance = 1.1

    return PersonaAffectContract(
        stance_hints=stance_hints,
        disallowed_tones=disallowed,
        preferred_length_min=preferred_min,
        preferred_length_max=preferred_max,
        opener_suppression_hints=opener_hints,
        ending_constraints=ending_constraints,
        mode_tolerance=mode_tolerance,
    )


def affect_contract_to_constraints(contract: PersonaAffectContract) -> DecisionConstraints:
    return DecisionConstraints(
        max_length=contract.preferred_length_max,
        min_length=contract.preferred_length_min,
        disallow_drift=True,
        disallow_service_tone=True,
    )


def build_variation_hint_from_contract(contract: PersonaAffectContract) -> str:
    if not contract.opener_suppression_hints:
        return ""
    labels = "、".join(contract.opener_suppression_hints[:3])
    return f"【开头去重】最近别再用这些开头：{labels}。"


def build_persona_affect_system_block(contract: PersonaAffectContract) -> str:
    """@ 闲聊专用：把 contract 的 stance/长度/禁腔调写入 system，而不只放 metadata 去重。"""
    lines = ["【本轮牛格塑形】"]
    seen: set[str] = set()
    for hint in contract.stance_hints:
        text = str(hint or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        lines.append(f"- {text}")

    if contract.preferred_length_max <= 16:
        length_line = "句长预算：优先 1 句，最多 2 句短口语。"
    elif contract.preferred_length_max <= 36:
        length_line = "句长预算：2 句内说完，像群友顺口接话。"
    else:
        length_line = "句长预算：可稍展开，但仍保持口语，别写分段小作文。"
    if length_line not in seen:
        lines.append(f"- {length_line}")

    if contract.disallowed_tones:
        tones = "、".join(contract.disallowed_tones)
        lines.append(f"- 避免腔调：{tones}；像群友顺口接话，别演成助手或导游。")

    for item in contract.ending_constraints:
        text = str(item or "").strip()
        if text and text not in seen:
            lines.append(f"- {text}")

    if len(lines) <= 1:
        lines.append("- 像本群常出现的接话：口语、直接，短句为主。")
    return "\n".join(lines)


def build_repeater_persona_affect_system_block(contract: PersonaAffectContract) -> str:
    lines = ["【接话塑形】"]
    seen: set[str] = set()
    for hint in contract.stance_hints[:3]:
        text = str(hint or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        lines.append(f"- {text}")

    if contract.preferred_length_max <= 16:
        length_line = "句长：1 句为主，最多 2 句短口语。"
    else:
        length_line = "句长：2 句内，像群友顺口接一句。"
    lines.extend([
        f"- {length_line}",
        "- 避免客服腔、总结腔、主动扯庆典或角色设定。",
    ])

    if contract.opener_suppression_hints:
        labels = "、".join(contract.opener_suppression_hints[:2])
        lines.append(f"- 别再用这些开头：{labels}")

    return "\n".join(lines)


def group_flavor_summary_from_style_snapshot(group_style: dict | None) -> str:
    if not isinstance(group_style, dict):
        return ""
    hints = group_style.get("hints")
    if not isinstance(hints, list):
        return ""
    parts = [str(item).strip() for item in hints if str(item).strip()]
    if not parts:
        return ""
    return "本群风格：" + "、".join(parts[:4])
