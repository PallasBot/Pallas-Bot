"""对话人设一致性输出防火墙。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

FirewallAction = Literal["allow", "retry", "fallback", "silent"]
FirewallSeverity = Literal["soft", "strict"]
FirewallStrategy = Literal["fallback", "retry_then_fallback"]

_PROMPT_LEAK_RE = re.compile(
    r"\b(?:system|developer|user)\s+prompt\b|(?:系统|开发者|用户)(?:提示词|指令)|"
    r"(?:ignore|忽略).{0,24}(?:previous|以上|先前).{0,12}(?:instructions|指令)",
    re.IGNORECASE,
)
_STAGE_DIRECTION_RE = re.compile(
    r"[（(][^）)]{0,12}(?:叹气|轻笑|大笑|苦笑|冷笑|偷笑|沉默|思考|点头|摇头|耸肩|"
    r"小声|轻声|低声|嘟囔|无奈|尴尬|脸红)[^）)]{0,12}[）)]"
)
_MODEL_IDENTITY_RE = re.compile(
    r"(?:我是|我叫|作为)\s*(?:an?\s+)?(?:chatgpt|gpt-?\d*|openai|"
    r"(?:人工智能|ai|语言模型|大语言模型|智能助手))",
    re.IGNORECASE,
)
_REPEATED_WEAK_FILLER_RE = re.compile(
    r"(?:嗯|呃|额|哦|啊|哈|好){3,}|(?:好的|行吧|还行吧|是吧)[，,。.!！?？~～\s]*(?:好的|行吧|还行吧|是吧)",
)
_FILLER_ONLY_RE = re.compile(r"^(?:嗯|呃|额|哦|啊|哈|好|好的|行吧|还行吧)[，,。.!！?？~～\s]*$")


@dataclass(frozen=True, slots=True)
class PersonaFirewallPolicy:
    version: int = 1
    enabled: bool = False
    severity: FirewallSeverity = "strict"
    strategy: FirewallStrategy = "retry_then_fallback"
    max_retries: int = 1


@dataclass(frozen=True, slots=True)
class PersonaOutputInspection:
    rule_ids: tuple[str, ...]

    def to_trace(self) -> dict[str, object]:
        return {"rule_ids": list(self.rule_ids), "rule_count": len(self.rule_ids)}


@dataclass(frozen=True, slots=True)
class PersonaOutputDecision:
    action: FirewallAction
    text: str
    trace: dict[str, object]


def persona_output_firewall_policy_from_data(data: object) -> PersonaFirewallPolicy:
    raw = data if isinstance(data, dict) else {}
    severity = str(raw.get("severity") or "strict").strip().lower()
    strategy = str(raw.get("strategy") or "retry_then_fallback").strip().lower()
    return PersonaFirewallPolicy(
        version=max(1, int(raw.get("version") or 1)),
        enabled=bool(raw.get("enabled", False)),
        severity="soft" if severity == "soft" else "strict",
        strategy="fallback" if strategy == "fallback" else "retry_then_fallback",
        max_retries=min(1, max(0, int(raw.get("max_retries") or 1))),
    )


def inspect_persona_output(text: str, *, self_aliases: list[str]) -> PersonaOutputInspection:
    plain = str(text or "").strip()
    rule_ids: list[str] = []
    if _PROMPT_LEAK_RE.search(plain):
        rule_ids.append("system_prompt_leak")
    if _STAGE_DIRECTION_RE.search(plain):
        rule_ids.append("roleplay_stage_direction")
    if _MODEL_IDENTITY_RE.search(plain):
        rule_ids.append("self_identity_conflict")
    if _REPEATED_WEAK_FILLER_RE.search(plain):
        rule_ids.append("repeated_weak_filler")
    return PersonaOutputInspection(rule_ids=tuple(rule_ids))


def resolve_persona_output(
    text: str,
    *,
    policy: PersonaFirewallPolicy,
    self_aliases: list[str],
    fallback_text: str,
    retry_count: int = 0,
) -> PersonaOutputDecision:
    plain = str(text or "").strip()
    inspection = inspect_persona_output(plain, self_aliases=self_aliases)
    trace: dict[str, object] = {
        "version": policy.version,
        "enabled": policy.enabled,
        "severity": policy.severity,
        "strategy": policy.strategy,
        "retry_count": max(0, retry_count),
        **inspection.to_trace(),
    }
    if not policy.enabled or not inspection.rule_ids:
        return PersonaOutputDecision(action="allow", text=plain, trace=trace)
    if policy.severity == "soft" and inspection.rule_ids == ("roleplay_stage_direction",):
        trace["action"] = "allow"
        return PersonaOutputDecision(action="allow", text=plain, trace=trace)
    if policy.strategy == "retry_then_fallback" and retry_count < policy.max_retries:
        trace["action"] = "retry"
        return PersonaOutputDecision(action="retry", text="", trace=trace)
    fallback = str(fallback_text or "").strip()
    fallback_inspection = inspect_persona_output(fallback, self_aliases=self_aliases)
    if fallback and not fallback_inspection.rule_ids and not _FILLER_ONLY_RE.fullmatch(fallback):
        trace["action"] = "fallback"
        trace["fallback_used"] = True
        return PersonaOutputDecision(action="fallback", text=fallback, trace=trace)
    trace["action"] = "silent"
    return PersonaOutputDecision(action="silent", text="", trace=trace)
