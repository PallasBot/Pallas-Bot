"""@对话回复门控：过滤纯表情/过短等不值得进 LLM 的消息。"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Literal

from pallas.product.llm.config import LlmConfig, get_llm_config
from pallas.product.persona.config import persona_affect_gate_enabled

if TYPE_CHECKING:
    from pallas.product.persona.model import ResolvedPersona

ReplyGateDecision = Literal["proceed", "skip", "defer"]

_CQ_CODE_RE = re.compile(r"\[CQ:[^\]]+\]", re.IGNORECASE)
_CQ_FACE_RE = re.compile(r"\[CQ:(?:face|bface|sface|rps|dice)[^\]]*\]", re.IGNORECASE)
_EMOJI_RE = re.compile(
    r"[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0000FE00-\U0000FE0F\U0000200D]+",
    re.UNICODE,
)


def strip_cq_codes(text: str) -> str:
    return _CQ_CODE_RE.sub("", text or "").strip()


def is_mostly_face_or_emoji(text: str) -> bool:
    raw = (text or "").strip()
    if not raw:
        return True
    if _CQ_FACE_RE.fullmatch(raw):
        return True
    plain = strip_cq_codes(raw)
    if not plain:
        return bool(_CQ_FACE_RE.search(raw))
    without_emoji = _EMOJI_RE.sub("", plain).strip()
    return not without_emoji


def persona_adjusted_min_chars(base_min: int, persona: ResolvedPersona | None) -> int:
    if persona is None or not persona_affect_gate_enabled():
        return base_min
    delta = int(round(-float(persona.warmth) * 2.0 - float(persona.assertiveness) * 0.8))
    return max(0, int(base_min) + delta)


def evaluate_llm_reply_gate(
    user_text: str,
    *,
    cfg: LlmConfig | None = None,
    persona: ResolvedPersona | None = None,
) -> ReplyGateDecision:
    c = cfg or get_llm_config()
    if not c.llm_reply_gate_enabled:
        return "proceed"
    plain = strip_cq_codes(user_text)
    if not plain and is_mostly_face_or_emoji(user_text):
        return "skip"
    if is_mostly_face_or_emoji(user_text):
        return "skip"
    min_chars = persona_adjusted_min_chars(max(0, int(c.llm_reply_gate_min_chars)), persona)
    if min_chars > 0 and len(plain) < min_chars:
        return "skip"
    return "proceed"
