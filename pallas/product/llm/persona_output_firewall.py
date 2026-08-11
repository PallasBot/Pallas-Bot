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
    r"(?:嗯|呃|额|哦|啊|哈|好|行){3,}|(?:好的|行吧|还行吧|是吧)[，,。.!！?？~～\s]*(?:好的|行吧|还行吧|是吧)",
)
_FILLER_ONLY_RE = re.compile(r"^(?:嗯|呃|额|哦|啊|哈|好|好的|行吧|还行吧)[，,。.!！?？~～\s]*$")
_ANIMAL_PERSONA_DRIFT_RE = re.compile(
    r"(?:我|本牛).{0,4}(?:牛角一甩|哞叫|反刍)|(?:牛角一甩|哞叫|反刍).{0,4}(?:我|本牛)|"
    r"(?:我要是|如果我是|假如我是|本牛).{0,16}(?:奶牛|牧场|牛棚|吃草|反刍|牛角|牛蹄)|"
    r"我(?:在|正|会|该|得|去).{0,12}(?:牛棚|吃草|反刍|牛角|牛蹄)"
)
_GENDER_IDENTITY_CONFLICT_RE = re.compile(r"(?:哥们|兄弟们|爷们|老子)(?:我|这|先|也|都|，|。|！|!|\s)")
_GENERIC_TEMPLATE_CLOSURE_RE = re.compile(
    r"(?:行吧|好吧)[，,。!！\s]*那?[旧就]当我没说[，,。!！\s]*(?:你|你们).{0,6}(?:乐呵|高兴|开心).{0,3}就行"
)
_SHORT_VENT_RE = re.compile(r"(?:烦|唉|累|难受|没绷住|服了|崩溃)[，,。.!！?？~～\s]*$")
_SHORT_VENT_GENERIC_QUESTION_RE = re.compile(
    r"^(?:咋了|怎么了|咋回事|什么情况|啥情况|然后呢|咋整)[，,。.!！?？~～\s]*$"
)
_SHORT_VENT_ADVICE_RE = re.compile(r"(?:^|[，,])\s*(?:先|要不|不如|可以|最好|建议|试试|别).{0,12}(?:吧|。|！|!|$)")
_PRESENCE_CHECK_RE = re.compile(r"(?:你|您)?(?:还)?(?:在|在线)吗[，,。.!！?？~～\s]*$")
_GENERIC_PRAISE_TERMS = ("有实力", "太强", "厉害啊", "厉害了")
_FACT_REPLY_COMPLIANCE_RE = re.compile(
    r"^(?:(?:改|行|好)(?:吧|呗)|(?:行|好)[，,\s]*(?:那)?(?:就)?这样吧)[，,。.!！?？~～\s]*$"
)
_SHORT_SOCIAL_DEFERENTIAL_PATTERNS = (
    re.compile(
        r"^(?:行(?:啊|吧)?|好(?:啊|吧)?)[，,\s]*那?你(?:就)?(?:骂|改)(?:吧|呗)"
        r"[，,。!！\s]*(?:我(?:听着|看着).*)?$"
    ),
    re.compile(r"^(?:你)?改吧[，,。!！\s]*(?:改完)?(?:喊我看|我等着).*$"),
)
_PERSONA_TOPIC_ANCHORS = (
    "米诺斯",
    "罗德岛",
    "干员",
    "博士",
    "美酒",
    "喝酒",
    "庆典",
    "戏剧",
    "竞赛",
    "酒",
)
_SHORT_SOCIAL_ROLEPLAY_EXPANSION_RE = re.compile(
    r"(?:给你)?竖(?:个)?大拇指|(?:拉|带|喊|叫)(?:上)?(?:我|我们)(?:去|来|一起|围观)"
)
_PARTICIPATION_INVITATION_TERMS = ("一起", "来不来", "去不去", "带上", "拉上", "喊上", "叫上", "陪我", "跟我")
_RECIPROCAL_SOCIAL_QUESTION_RE = re.compile(
    r"(?:^|[。！？!?]\s*)(?:你呢|你(?:那边)?(?:怎么样|咋样)|你吃没|你吃了吗)[？?]\s*$"
)
_SHORT_SOCIAL_ACTIONS = frozenset({"ACK", "AFFECTION", "JOKE"})
_RECIPROCAL_QUESTION_ACTIONS = _SHORT_SOCIAL_ACTIONS | {"STANCE", "ANSWER"}
_HARD_PRESSURE_CHAT_RE = re.compile(r"(?:少废话|闭嘴|滚|自己想|别来烦我|别烦我|爱咋咋地)[，,。!！\s]*$")
_PRICKLY_CHAT_RE = re.compile(r"(?:关我什么事|与我无关|不关我的事|懒得理你|别找我)[，,。!！\s]*$")
_SUPPORTIVE_CONTEXT_DEFLECTION_RE = re.compile(r"(?:哎呀)?这个我不会嘛[，,。!！\s]*$")
_SUPPORTIVE_HELP_REQUEST_RE = re.compile(
    r"(?:我|自己)不知道(?:该)?怎么办|(?:我|自己)不知所措[，,。！？!?\s]{0,4}(?:我)?该怎么办|(?:我|自己)撑不住"
)


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
    quality_rule_ids: tuple[str, ...] = ()
    persona_topic_terms: tuple[str, ...] = ()
    unprompted_self_aliases: tuple[str, ...] = ()
    short_vent: bool = False
    social_action: str = ""

    def to_trace(self) -> dict[str, object]:
        chat_quality: dict[str, object] = {
            "short_vent": self.short_vent,
            "social_action": self.social_action,
            "rule_ids": list(self.quality_rule_ids),
        }
        if self.persona_topic_terms:
            chat_quality["persona_topic_terms"] = list(self.persona_topic_terms)
        if self.unprompted_self_aliases:
            chat_quality["unprompted_self_aliases"] = list(self.unprompted_self_aliases)
        return {
            "rule_ids": list(self.rule_ids),
            "rule_count": len(self.rule_ids),
            "chat_quality": chat_quality,
        }


@dataclass(frozen=True, slots=True)
class PersonaOutputDecision:
    action: FirewallAction
    text: str
    trace: dict[str, object]


def persona_output_firewall_policy_from_data(data: object) -> PersonaFirewallPolicy:
    raw = data if isinstance(data, dict) else {}
    severity = str(raw.get("severity") or "strict").strip().lower()
    strategy = str(raw.get("strategy") or "retry_then_fallback").strip().lower()
    enabled_raw = raw.get("enabled", True)
    if isinstance(enabled_raw, str):
        enabled = enabled_raw.strip().lower() in {"1", "true", "yes", "on"}
    else:
        enabled = bool(enabled_raw)
    try:
        max_retries = int(raw["max_retries"]) if "max_retries" in raw else 1
    except (TypeError, ValueError):
        max_retries = 1
    return PersonaFirewallPolicy(
        version=max(1, int(raw.get("version") or 1)),
        enabled=enabled,
        severity="soft" if severity == "soft" else "strict",
        strategy="fallback" if strategy == "fallback" else "retry_then_fallback",
        max_retries=min(1, max(0, max_retries)),
    )


def inspect_persona_output(
    text: str,
    *,
    self_aliases: list[str],
    current_user_text: str = "",
    social_action: str = "",
    reply_target: str = "",
) -> PersonaOutputInspection:
    plain = str(text or "").strip()
    rule_ids: list[str] = []
    quality_rule_ids: list[str] = []
    current = str(current_user_text or "").strip().rsplit("\n", 1)[-1].strip()
    short_vent = len(current) <= 24 and bool(_SHORT_VENT_RE.search(current))
    is_presence_check = bool(_PRESENCE_CHECK_RE.search(current))
    action = str(social_action or "").strip().upper()
    target = str(reply_target or "").strip().lower()
    user_is_hostile = any(term in current for term in ("滚", "闭嘴", "别烦我", "去死"))
    current_has_persona_topic = any(anchor in current for anchor in _PERSONA_TOPIC_ANCHORS)
    persona_topic_terms = ()
    if not current_has_persona_topic:
        persona_topic_terms = tuple(anchor for anchor in _PERSONA_TOPIC_ANCHORS if anchor in plain)
    unprompted_self_aliases = _find_unprompted_self_aliases(
        plain,
        current_user_text=current,
        self_aliases=self_aliases,
    )
    if _PROMPT_LEAK_RE.search(plain):
        rule_ids.append("system_prompt_leak")
    if _STAGE_DIRECTION_RE.search(plain):
        rule_ids.append("roleplay_stage_direction")
    if _MODEL_IDENTITY_RE.search(plain):
        rule_ids.append("self_identity_conflict")
    if _REPEATED_WEAK_FILLER_RE.search(plain):
        rule_ids.append("repeated_weak_filler")
    if _ANIMAL_PERSONA_DRIFT_RE.search(plain):
        rule_ids.append("animal_persona_drift")
    if _GENDER_IDENTITY_CONFLICT_RE.search(plain):
        rule_ids.append("gender_identity_conflict")
    if _GENERIC_TEMPLATE_CLOSURE_RE.search(plain):
        rule_ids.append("generic_template_closure")
    if short_vent and len(plain) > 16:
        quality_rule_ids.append("short_vent_overexplained")
        rule_ids.append("short_vent_overexplained")
    if short_vent and _SHORT_VENT_GENERIC_QUESTION_RE.fullmatch(plain):
        quality_rule_ids.append("short_vent_generic_question")
        rule_ids.append("short_vent_generic_question")
    if short_vent and target == "emotion" and _SHORT_VENT_ADVICE_RE.search(plain):
        quality_rule_ids.append("short_vent_unsolicited_advice")
        rule_ids.append("short_vent_unsolicited_advice")
    if is_presence_check and len(plain) > 4:
        quality_rule_ids.append("presence_check_overexplained")
        rule_ids.append("presence_check_overexplained")
    if (
        (target in {"emotion", "help"} or (target == "answer" and _SUPPORTIVE_HELP_REQUEST_RE.search(current)))
        and action in {"ACK", "ANSWER", "STANCE"}
        and _SUPPORTIVE_CONTEXT_DEFLECTION_RE.fullmatch(plain)
    ):
        quality_rule_ids.append("supportive_context_deflection")
        rule_ids.append("supportive_context_deflection")
    if (
        target == "fact"
        and any(term in plain for term in _GENERIC_PRAISE_TERMS)
        and not any(term in current for term in _GENERIC_PRAISE_TERMS)
    ):
        quality_rule_ids.append("fact_reply_ungrounded_praise")
        rule_ids.append("fact_reply_ungrounded_praise")
    if target == "fact" and len(plain) > 14:
        quality_rule_ids.append("fact_reply_overextended")
        rule_ids.append("fact_reply_overextended")
    if target == "fact" and _FACT_REPLY_COMPLIANCE_RE.fullmatch(plain):
        quality_rule_ids.append("fact_reply_compliance_template")
        rule_ids.append("fact_reply_compliance_template")
    if action in _SHORT_SOCIAL_ACTIONS and any(
        pattern.fullmatch(plain) for pattern in _SHORT_SOCIAL_DEFERENTIAL_PATTERNS
    ):
        quality_rule_ids.append("short_social_deferential_template")
        rule_ids.append("short_social_deferential_template")
    if action in _SHORT_SOCIAL_ACTIONS and persona_topic_terms:
        quality_rule_ids.append("persona_topic_hijack")
        rule_ids.append("persona_topic_hijack")
    if action in _SHORT_SOCIAL_ACTIONS and unprompted_self_aliases:
        quality_rule_ids.append("unprompted_self_alias")
        rule_ids.append("unprompted_self_alias")
    if action in _RECIPROCAL_QUESTION_ACTIONS and _RECIPROCAL_SOCIAL_QUESTION_RE.search(plain):
        quality_rule_ids.append("reciprocal_social_question")
        rule_ids.append("reciprocal_social_question")
    if (
        action in _SHORT_SOCIAL_ACTIONS
        and not any(term in current for term in _PARTICIPATION_INVITATION_TERMS)
        and _SHORT_SOCIAL_ROLEPLAY_EXPANSION_RE.search(plain)
    ):
        quality_rule_ids.append("short_social_roleplay_expansion")
        rule_ids.append("short_social_roleplay_expansion")
    if action in {"ACK", "ANSWER", "STANCE"} and _HARD_PRESSURE_CHAT_RE.search(plain):
        quality_rule_ids.append("chat_hard_pressure_tone")
        rule_ids.append("chat_hard_pressure_tone")
    if action in {"ACK", "ANSWER", "STANCE"} and not user_is_hostile and _PRICKLY_CHAT_RE.search(plain):
        quality_rule_ids.append("chat_prickly_tone")
        rule_ids.append("chat_prickly_tone")
    return PersonaOutputInspection(
        rule_ids=tuple(rule_ids),
        quality_rule_ids=tuple(quality_rule_ids),
        persona_topic_terms=persona_topic_terms,
        unprompted_self_aliases=unprompted_self_aliases,
        short_vent=short_vent,
        social_action=action,
    )


def _find_unprompted_self_aliases(
    text: str,
    *,
    current_user_text: str,
    self_aliases: list[str],
) -> tuple[str, ...]:
    current = current_user_text.casefold()
    plain = text.casefold()
    found: list[str] = []
    for raw_alias in self_aliases:
        alias = str(raw_alias or "").strip()
        if len(alias) < 2 or alias.casefold() in current:
            continue
        escaped = re.escape(alias)
        if re.search(rf"(?:^|[，,。.!！?？\s]){escaped}(?:都|也|先|在|呢|来|去|要|得|能|会|还|又|已经|正在|这)", plain):
            found.append(alias)
            continue
        if re.search(rf"(?:拉|带|喊|叫).{{0,3}}{escaped}(?:去|来|看看|一下)?", plain):
            found.append(alias)
    return tuple(found)


def resolve_persona_output(
    text: str,
    *,
    policy: PersonaFirewallPolicy,
    self_aliases: list[str],
    fallback_text: str,
    retry_count: int = 0,
    current_user_text: str = "",
    social_action: str = "",
    reply_target: str = "",
) -> PersonaOutputDecision:
    plain = str(text or "").strip()
    inspection = inspect_persona_output(
        plain,
        self_aliases=self_aliases,
        current_user_text=current_user_text,
        social_action=social_action,
        reply_target=reply_target,
    )
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
    if not fallback and "presence_check_overexplained" in inspection.rule_ids:
        fallback = "在"
    if not fallback and inspection.short_vent and str(reply_target or "").strip().lower() == "emotion":
        fallback = "确实烦。"
    fallback_inspection = inspect_persona_output(
        fallback,
        self_aliases=self_aliases,
        current_user_text=current_user_text,
        social_action=social_action,
        reply_target=reply_target,
    )
    if fallback and not fallback_inspection.rule_ids and not _FILLER_ONLY_RE.fullmatch(fallback):
        trace["action"] = "fallback"
        trace["fallback_used"] = True
        return PersonaOutputDecision(action="fallback", text=fallback, trace=trace)
    trace["action"] = "silent"
    return PersonaOutputDecision(action="silent", text="", trace=trace)


def persona_output_retry_instruction(rule_ids: tuple[str, ...] | list[str]) -> str:
    """Describe the narrowest rewrite needed for the failed output rules."""
    rules = set(rule_ids)
    if "short_vent_overexplained" in rules:
        return "上一句把短抱怨说得太满了。只顺手接一句，不给建议、总结或收尾。"
    if "short_vent_generic_question" in rules:
        return "上一句只是泛问，没接住短抱怨。顺手接一句，不反问、不总结、不提建议。"
    if "short_vent_unsolicited_advice" in rules:
        return "上一句擅自安排了下一步。只接住这句情绪，不提建议、做法或时间安排。"
    if "presence_check_overexplained" in rules:
        return "上一句在确认是否在线时补了状态和反问。只回答是否在，四字以内，不追加任何话。"
    if "fact_reply_ungrounded_praise" in rules:
        return "上一句无根据地夸人了。只接当前这句话，不泛夸、不鼓励。"
    if "fact_reply_overextended" in rules:
        return "上一句接得太长。十四字以内直接给完整短结论，不要先说行/好，不补理由、邀请或新安排。"
    if "fact_reply_compliance_template" in rules:
        return "上一句只是顺着安排的模板句。换成直接反应，不用改吧、改呗、行吧或好吧。"
    if "short_social_deferential_template" in rules:
        return "上一句太像顺着哄人或等对方安排了。换成贴当前话题的短句，不邀请对方继续。"
    if "persona_topic_hijack" in rules:
        return "上一句把无关角色设定带成了新话题。只接当前这句话，不提角色背景、地点、酒或邀约。"
    if "unprompted_self_alias" in rules:
        return "上一句无故把自己的称呼当第三人称说了。只用第一人称接当前这句话，不提自己的名字或别名。"
    if "short_social_roleplay_expansion" in rules:
        return "上一句凭空加了表演式夸赞或邀约。只接当前这句话，不加动作描写、夸张鼓励或新安排。"
    if "reciprocal_social_question" in rules:
        return "上一句回答后又用礼貌反问把话抛回去了。保留前面的回应，直接收住；不问你呢、你怎么样或你吃没。"
    return "请直接用当前角色自然重述上一句，不要提及提示词、系统、模型或舞台动作。"


def redact_agent_trace_for_firewall(agent_trace: object) -> dict[str, object] | None:
    if not isinstance(agent_trace, dict):
        return None
    rounds: list[dict[str, object]] = []
    for raw_round in agent_trace.get("rounds") or []:
        if not isinstance(raw_round, dict):
            continue
        calls: list[dict[str, object]] = []
        for raw_call in raw_round.get("calls") or []:
            if not isinstance(raw_call, dict):
                continue
            calls.append({
                "tool": str(raw_call.get("tool") or ""),
                "provider_name": str(raw_call.get("provider_name") or ""),
                "args_keys": [str(item) for item in raw_call.get("args_keys") or []],
                "ok": bool(raw_call.get("ok")),
            })
        rounds.append({
            "round": int(raw_round.get("round") or 0),
            "tool_calls": [str(item) for item in raw_round.get("tool_calls") or []],
            "calls": calls,
        })
    return {
        "final_stage": str(agent_trace.get("final_stage") or ""),
        "tool_call_count": int(agent_trace.get("tool_call_count") or 0),
        "rounds": rounds,
        "status": str(agent_trace.get("status") or ""),
        "tool_loop_enabled": bool(agent_trace.get("tool_loop_enabled")),
        "tool_schema_count": int(agent_trace.get("tool_schema_count") or 0),
        "tool_names": [str(item) for item in agent_trace.get("tool_names") or []],
        "activated_tools": [str(item) for item in agent_trace.get("activated_tools") or []],
        "reply_source": str(agent_trace.get("reply_source") or ""),
    }
