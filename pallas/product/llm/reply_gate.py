"""@对话回复门控：过滤纯表情/过短等不值得进 LLM 的消息。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from pallas.product.llm.config import LlmConfig, get_llm_config
from pallas.product.llm.shut_up import is_shut_up_text
from pallas.product.persona.config import persona_affect_gate_enabled

if TYPE_CHECKING:
    from pallas.product.persona.model import ResolvedPersona

ReplyGateDecision = Literal["proceed", "skip", "defer"]
ReplyGateSkipReason = Literal[
    "face",
    "noise",
    "short",
    "bystander",
    "incomplete",
    "shut_up",
]


@dataclass(frozen=True, slots=True)
class ReplyGateResult:
    decision: ReplyGateDecision
    reason: str = ""


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


def is_shut_up_request(text: str) -> bool:
    return is_shut_up_text(strip_cq_codes(text))


def persona_adjusted_min_chars(base_min: int, persona: ResolvedPersona | None) -> int:
    if persona is None or not persona_affect_gate_enabled():
        return base_min
    delta = int(round(-float(persona.warmth) * 2.0 - float(persona.assertiveness) * 0.8))
    return max(0, int(base_min) + delta)


def evaluate_llm_reply_gate_result(
    user_text: str,
    *,
    cfg: LlmConfig | None = None,
    persona: ResolvedPersona | None = None,
    bot_id: int | None = None,
    group_id: int | None = None,
) -> ReplyGateResult:
    from pallas.product.llm.reply_necessity import (
        is_bystander_plain_text,
        is_incomplete_utterance,
        is_noise_fragment,
    )
    from pallas.product.llm.silence import trigger_silence

    c = cfg or get_llm_config()
    if not c.llm_reply_gate_enabled:
        return ReplyGateResult("proceed", "disabled")
    plain = strip_cq_codes(user_text)
    if is_shut_up_request(user_text):
        if c.llm_shut_up_silence_enabled and bot_id is not None and group_id is not None:
            trigger_silence(
                bot_id,
                group_id,
                min_sec=int(c.llm_shut_up_silence_min_sec),
                max_sec=int(c.llm_shut_up_silence_max_sec),
            )
        return ReplyGateResult("skip", "shut_up")
    if not plain and is_mostly_face_or_emoji(user_text):
        return ReplyGateResult("skip", "face")
    if is_mostly_face_or_emoji(user_text):
        return ReplyGateResult("skip", "face")
    if is_noise_fragment(plain):
        return ReplyGateResult("skip", "noise")
    if is_incomplete_utterance(plain):
        return ReplyGateResult("skip", "incomplete")
    if is_bystander_plain_text(user_text, bot_id=bot_id):
        return ReplyGateResult("skip", "bystander")
    min_chars = persona_adjusted_min_chars(max(0, int(c.llm_reply_gate_min_chars)), persona)
    if min_chars > 0 and len(plain) < min_chars:
        return ReplyGateResult("skip", "short")
    return ReplyGateResult("proceed", "ok")


def evaluate_llm_reply_gate(
    user_text: str,
    *,
    cfg: LlmConfig | None = None,
    persona: ResolvedPersona | None = None,
    bot_id: int | None = None,
    group_id: int | None = None,
) -> ReplyGateDecision:
    return evaluate_llm_reply_gate_result(
        user_text,
        cfg=cfg,
        persona=persona,
        bot_id=bot_id,
        group_id=group_id,
    ).decision


def reply_gate_skip_metric(reason: str) -> str | None:
    key = str(reason or "").strip().lower()
    mapping = {
        "face": "reply_gate_skip_face",
        "noise": "reply_gate_skip_noise",
        "short": "reply_gate_skip_short",
        "bystander": "reply_gate_skip_bystander",
        "incomplete": "reply_gate_skip_incomplete",
        "shut_up": "reply_gate_skip_shut_up",
    }
    return mapping.get(key)
