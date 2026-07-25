"""关系事实小档案：同槽覆盖、称呼解析与注入引导（人物事实向，非好感标量）。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from pallas.product.llm.memory.relationship import split_relationship_facts
from pallas.product.persona.prompt_guard import sanitize_prompt_literal

_CALL_AS_RE = re.compile(r"^希望被叫作(?P<name>.+)$")
_AVOID_CALL_RE = re.compile(r"^不喜欢被叫作(?P<name>.+)$")
_ROLE_RE = re.compile(r"^是本群(?P<label>.+)$")

# 同槽只保留最新一条
_SINGLETON_SLOTS = frozenset({"call_as", "role", "no_nickname", "direct"})


def relationship_fact_slot(fact: str) -> str | None:
    text = (fact or "").strip()
    if not text:
        return None
    if text.startswith("希望被叫作"):
        return "call_as"
    if text.startswith("是本群"):
        return "role"
    if text == "不喜欢被叫外号":
        return "no_nickname"
    if text == "偏好直接沟通":
        return "direct"
    if text.startswith("不喜欢被叫作"):
        name = text.removeprefix("不喜欢被叫作").strip()
        return f"avoid_call:{name.casefold()}" if name else "avoid_call"
    return None


def apply_relationship_fact_slots(parts: list[str], incoming: list[str]) -> list[str]:
    """合并事实列表：单槽覆盖、同避称覆盖、其余按原文去重追加。"""
    kept = list(parts)
    seen = {item.casefold() for item in kept}
    for item in incoming:
        text = (item or "").strip()
        if not text:
            continue
        slot = relationship_fact_slot(text)
        if slot in _SINGLETON_SLOTS or (slot is not None and slot.startswith("avoid_call:")):
            kept = [prev for prev in kept if relationship_fact_slot(prev) != slot]
            seen = {prev.casefold() for prev in kept}
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        kept.append(text)
    return kept


@dataclass(frozen=True, slots=True)
class RelationshipFactView:
    facts: list[str] = field(default_factory=list)
    preferred_name: str = ""
    avoid_names: list[str] = field(default_factory=list)
    role_label: str = ""
    prefer_direct: bool = False
    dislike_nickname: bool = False

    @property
    def has_facts(self) -> bool:
        return bool(self.facts)


def parse_relationship_fact_view(content: str) -> RelationshipFactView:
    facts = split_relationship_facts(content)
    preferred = ""
    avoid: list[str] = []
    role = ""
    prefer_direct = False
    dislike_nickname = False
    for item in facts:
        if matched := _CALL_AS_RE.match(item):
            preferred = str(matched.group("name") or "").strip()
            continue
        if matched := _AVOID_CALL_RE.match(item):
            name = str(matched.group("name") or "").strip()
            if name and name not in avoid:
                avoid.append(name)
            continue
        if matched := _ROLE_RE.match(item):
            role = str(matched.group("label") or "").strip()
            continue
        if item == "偏好直接沟通":
            prefer_direct = True
            continue
        if item == "不喜欢被叫外号":
            dislike_nickname = True
    return RelationshipFactView(
        facts=facts,
        preferred_name=preferred,
        avoid_names=avoid,
        role_label=role,
        prefer_direct=prefer_direct,
        dislike_nickname=dislike_nickname,
    )


def build_relationship_guidance_lines(view: RelationshipFactView) -> list[str]:
    """面向模型的行动提示：怎么称呼、怎么接，不念档案。"""
    lines: list[str] = []
    if view.preferred_name:
        name = sanitize_prompt_literal(view.preferred_name, max_len=16)
        if name:
            lines.append(f"称呼对方时优先用「{name}」，别生硬复述档案。")
    if view.avoid_names:
        labels = "、".join(
            item for item in (sanitize_prompt_literal(name, max_len=16) for name in view.avoid_names[:3]) if item
        )
        if labels:
            lines.append(f"避免称呼：{labels}。")
    if view.dislike_nickname:
        lines.append("不要给对方起外号。")
    if view.prefer_direct:
        lines.append("对方偏好直接沟通，少客套铺垫。")
    if view.role_label and not view.preferred_name:
        role = sanitize_prompt_literal(view.role_label, max_len=12)
        if role:
            lines.append(f"对方是本群{role}，可自然认身份，别官腔。")
    if view.has_facts and not lines:
        lines.append("已有稳定印象，可自然使用下列事实，勿当自我介绍念出来。")
    return lines
