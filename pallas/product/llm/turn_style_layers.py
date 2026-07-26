"""本轮行为 / 措辞分层，以及同句重回、概率换风格辅助。"""

from __future__ import annotations

import random
import re
from typing import Any

from pallas.product.persona.prompt_guard import sanitize_prompt_literal

_WS_RE = re.compile(r"\s+")

# 概率换风格：默认约 1/4 轮注入一条临时措辞提示
DEFAULT_ALT_STYLE_PROBABILITY = 0.25

_ALT_REPLY_STYLES: tuple[str, ...] = (
    "这轮稍微冷一点、短一点，少解释。",
    "这轮可以更俏皮一点，但仍是口语短句。",
    "这轮偏认真直接，少用语气词堆砌。",
    "这轮用半句或反问收口，别起手软答应（行行行/还行吧）。",
    "这轮顺着对方最后一个词接，不要换话题。",
)


def normalize_utterance_key(text: str, *, max_len: int = 80) -> str:
    plain = _WS_RE.sub("", str(text or "").strip()).lower()
    return plain[: max(8, int(max_len))]


def find_previous_reply_for_utterance(
    user_text: str,
    *,
    recent_turns: list[Any] | None = None,
    behavior_runs: list[Any] | None = None,
) -> str:
    """若近期已对同一（或极近）用户句回过，返回上次回复正文。"""
    key = normalize_utterance_key(user_text)
    if len(key) < 2:
        return ""

    for run in reversed(list(behavior_runs or [])):
        run_key = normalize_utterance_key(str(getattr(run, "user_text", "") or ""))
        reply = str(getattr(run, "reply_text", "") or "").strip()
        if not reply or len(run_key) < 2:
            continue
        if run_key == key or (len(key) >= 6 and (key in run_key or run_key in key)):
            return sanitize_prompt_literal(reply, max_len=120)

    turns = list(recent_turns or [])
    for index in range(len(turns) - 1, -1, -1):
        turn = turns[index]
        if str(getattr(turn, "role", "") or "").strip() != "user":
            continue
        turn_key = normalize_utterance_key(str(getattr(turn, "content", "") or ""))
        if not turn_key or not (turn_key == key or (len(key) >= 6 and (key in turn_key or turn_key in key))):
            continue
        for follow in turns[index + 1 :]:
            if str(getattr(follow, "role", "") or "").strip() != "assistant":
                continue
            reply = str(getattr(follow, "content", "") or "").strip()
            if reply:
                return sanitize_prompt_literal(reply, max_len=120)
            break
    return ""


def build_same_utterance_redup_hint(*, user_text: str, previous_reply: str) -> str:
    prev = sanitize_prompt_literal(str(previous_reply or "").strip(), max_len=120)
    if not prev:
        return ""
    trigger = sanitize_prompt_literal(str(user_text or "").strip(), max_len=40)
    prefix = f"用户又提了类似「{trigger}」。" if trigger else "用户又提了类似内容。"
    return f"【同句重回】{prefix}你上次回过：「{prev}」。这次换说法，不要复述上一句，也不要用同一套起手。"


def build_probabilistic_alt_style_hint(
    *,
    probability: float = DEFAULT_ALT_STYLE_PROBABILITY,
    rng: random.Random | None = None,
) -> str:
    """以一定概率注入临时措辞风格（不进静态人设）。"""
    rate = max(0.0, min(1.0, float(probability)))
    dice = rng if rng is not None else random
    if rate <= 0 or dice.random() >= rate:
        return ""
    style = dice.choice(_ALT_REPLY_STYLES)
    return f"【本轮临时措辞】{style}请视情况自然使用，不要照抄本提示。"


def build_turn_behavior_block(*parts: str) -> str:
    """行为层：何时/怎么接，不管具体口癖措辞。"""
    lines = [str(part or "").strip() for part in parts if str(part or "").strip()]
    if not lines:
        return ""
    body = "\n".join(lines)
    return f"【本轮行为（只管怎么接，不管具体措辞）】\n{body}"


def build_turn_wording_user_hints(*parts: str) -> list[str]:
    """措辞相关提示：作为临时 user 消息插入，不写进静态人设。"""
    out: list[str] = []
    for part in parts:
        text = str(part or "").strip()
        if text:
            out.append(text)
    return out


def merge_style_hints_before_last_user(
    messages: list[Any],
    hints: list[str],
    *,
    message_cls: type | None = None,
) -> list[Any]:
    """把措辞提示插在最后一条 user 消息之前。"""
    cleaned = [str(item or "").strip() for item in hints if str(item or "").strip()]
    if not cleaned or not messages:
        return messages
    cls = message_cls
    if cls is None:
        from pallas.product.llm.models import ChatCompletionMessage

        cls = ChatCompletionMessage
    last = messages[-1]
    if str(getattr(last, "role", "") or "").strip() != "user":
        return list(messages) + [cls(role="user", content=item) for item in cleaned]
    return [
        *messages[:-1],
        *[cls(role="user", content=item) for item in cleaned],
        last,
    ]
