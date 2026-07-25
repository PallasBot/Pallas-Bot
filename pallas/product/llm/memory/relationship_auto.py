"""关系备注弱观察与硬触发后规则抽取（默认规则-only，不做 LLM 抽取）。"""

from __future__ import annotations

import re
from dataclasses import dataclass

from pallas.product.llm.memory.relationship import (
    relationship_note_has_value,
    relationship_teach_likely,
)

_MAX_FACT_LEN = 48
_AFFECT_STEP = 0.03

_OBSERVE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^我是(?:这个群的|本群的|本群)?(?P<label>群主|群管|管理员|管理)$"), "是本群{label}"),
    (re.compile(r"^我(?:就是|乃)(?:这个群的|本群的|本群)?(?P<label>群主|群管|管理员|管理)$"), "是本群{label}"),
    (re.compile(r"^(?:以后)?(?:请)?叫我(?P<name>[^，,。！!\s]{1,12})$"), "希望被叫作{name}"),
    (re.compile(r"^别(?:再)?叫我(?P<name>[^，,。！!\s]{1,12})$"), "不喜欢被叫作{name}"),
)

_WARMTH_POS = ("喜欢你", "最喜欢你", "贴贴", "摸摸", "你好棒", "爱你", "想你了", "你真好")
_WARMTH_NEG = ("滚", "别烦我", "讨厌你", "闭嘴", "走开", "别理我", "烦死你")
_ASSERT_POS = ("来啊", "敢不敢", "你凶", "别装", "顶你")
_ASSERT_NEG = ("对不起", "抱歉", "别生气", "求你了")


@dataclass(frozen=True, slots=True)
class RelationshipAutoUpdate:
    fact: str | None = None
    warmth_delta_add: float = 0.0
    assertiveness_delta_add: float = 0.0

    @property
    def has_change(self) -> bool:
        return bool(self.fact) or self.warmth_delta_add != 0.0 or self.assertiveness_delta_add != 0.0


def _normalize_label(label: str) -> str:
    text = (label or "").strip()
    if text in {"群管", "管理员", "管理"}:
        return "群管"
    return text


def parse_relationship_observe(plain_text: str) -> str | None:
    """弱观察：说话人自报稳定身份/称呼偏好，返回可入库事实短句。"""
    body = (plain_text or "").strip()
    if not body or relationship_teach_likely(body):
        return None
    if any(token in body for token in ("吗", "呢", "？", "?", "怎么", "为什么")):
        return None
    for pattern, template in _OBSERVE_PATTERNS:
        matched = pattern.match(body)
        if matched is None:
            continue
        values = {key: str(matched.group(key) or "").strip() for key in matched.groupdict()}
        if "label" in values:
            values["label"] = _normalize_label(values["label"])
        if "name" in values and (len(values["name"]) < 1 or values["name"] in {"你", "我", "他", "她"}):
            return None
        fact = template.format(**values).strip()
        if not relationship_note_has_value(fact) or len(fact) > _MAX_FACT_LEN:
            return None
        return fact
    return None


def extract_relationship_attitude_delta(plain_text: str) -> tuple[float, float]:
    """明确亲昵/疏远信号时给小幅态度偏置；瞬时情绪词不写事实，只调轴。"""
    body = (plain_text or "").strip()
    if not body or len(body) > 40:
        return 0.0, 0.0
    warmth = 0.0
    assertiveness = 0.0
    if any(token in body for token in _WARMTH_POS):
        warmth += _AFFECT_STEP
    if any(token in body for token in _WARMTH_NEG):
        warmth -= _AFFECT_STEP
    if any(token in body for token in _ASSERT_POS):
        assertiveness += _AFFECT_STEP
    if any(token in body for token in _ASSERT_NEG):
        assertiveness -= _AFFECT_STEP
    return round(warmth, 3), round(assertiveness, 3)


def extract_relationship_auto(plain_text: str, *, allow_affect: bool = True) -> RelationshipAutoUpdate | None:
    """硬触发后规则抽取：事实优先观察句式；态度仅明确信号。"""
    fact = parse_relationship_observe(plain_text)
    warmth = 0.0
    assertiveness = 0.0
    if allow_affect:
        warmth, assertiveness = extract_relationship_attitude_delta(plain_text)
    update = RelationshipAutoUpdate(
        fact=fact,
        warmth_delta_add=warmth,
        assertiveness_delta_add=assertiveness,
    )
    return update if update.has_change else None
