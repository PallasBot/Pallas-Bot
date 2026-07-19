"""@闲聊短期去重与群聊节奏辅助。"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pallas.product.llm.session_store import LlmChatTurn

_DIRECT_REPEATED_OPENERS = (
    "哈喽",
    "其实",
    "这倒是",
    "怎么说呢",
    "感觉",
    "我觉得",
    "确实",
    "一般来说",
    "行吧",
)
_LAUGH_OPENER_RE = re.compile(r"^(哈哈+|呵呵+|嘿嘿+)")
_SIGH_OPENER_RE = re.compile(r"^(欸|哎|唉|呃|额)+")
_ANIMAL_OPENER_RE = re.compile(r"^(哞~|喵~|喵呜~|哞呜~)")
_TILDE_OPENER_RE = re.compile(r"^([\u4e00-\u9fff]{1,2})~")
_KAOMOJI_SUFFIX_RE = re.compile(r"\(\*[^)]{1,16}\*\)\s*$")

_USER_WAIT_SUFFIXES = ("?", "？", "...", "…", "、")
_USER_WAIT_TOKENS = ("等等", "等下", "先别", "我补一句", "还有", "然后")
_STRUCTURE_MARKERS = ("先", "别", "可以", "不用", "慢慢", "一下", "这事", "你先")
_GENERIC_PREFIX_MIN_LEN = 3
_GENERIC_PREFIX_MAX_LEN = 4


def should_wait_for_more(user_text: str) -> bool:
    text = str(user_text or "").strip()
    if not text:
        return False
    if any(text.endswith(token) for token in _USER_WAIT_SUFFIXES):
        return True
    return any(token in text[-8:] for token in _USER_WAIT_TOKENS)


def has_kaomoji_suffix(text: str) -> bool:
    return bool(_KAOMOJI_SUFFIX_RE.search(str(text or "").strip()))


def repeated_assistant_openers(turns: list[LlmChatTurn], *, limit: int = 3) -> list[str]:
    seen: list[str] = []
    for turn in reversed(turns):
        if turn.role != "assistant":
            continue
        text = str(turn.content or "").strip()
        if not text:
            continue
        opener = classify_repeated_opener(text)
        if opener and opener not in seen:
            seen.append(opener)
        if len(seen) >= limit:
            break
    return seen


def classify_repeated_opener(text: str) -> str:
    plain = str(text or "").strip()
    if not plain:
        return ""
    animal = _ANIMAL_OPENER_RE.match(plain)
    if animal:
        return animal.group(1)
    if _LAUGH_OPENER_RE.match(plain):
        return "哈哈类"
    if _SIGH_OPENER_RE.match(plain):
        return "语气词类"
    direct = next((item for item in _DIRECT_REPEATED_OPENERS if plain.startswith(item)), "")
    if direct:
        return direct
    return normalize_generic_prefix(plain)


def normalize_generic_prefix(text: str) -> str:
    plain = str(text or "").strip()
    if len(plain) < _GENERIC_PREFIX_MIN_LEN:
        return ""
    tilde = _TILDE_OPENER_RE.match(plain)
    if tilde:
        prefix = tilde.group(0)
        if len(prefix) >= _GENERIC_PREFIX_MIN_LEN:
            return prefix
    prefix_chars: list[str] = []
    for char in plain:
        if char in "，,。！？!?~～…：:；;、()（）[]【】<>《》\"'“”‘’ ":
            break
        prefix_chars.append(char)
        if len(prefix_chars) >= _GENERIC_PREFIX_MAX_LEN:
            break
    prefix = "".join(prefix_chars).strip()
    if len(prefix) < _GENERIC_PREFIX_MIN_LEN:
        return ""
    if prefix.isdigit() or not any("\u4e00" <= char <= "\u9fff" for char in prefix):
        return ""
    if prefix in {"我是", "你是", "这个", "那个", "不是", "就是"}:
        return ""
    return prefix


def recent_assistant_endings(turns: list[LlmChatTurn], *, limit: int = 3) -> list[str]:
    seen: list[str] = []
    for turn in reversed(turns):
        if turn.role != "assistant":
            continue
        text = str(turn.content or "").strip()
        if not text or has_kaomoji_suffix(text):
            continue
        compact = text.rstrip("。！？!?~～…，,、 ")
        if not compact:
            continue
        ending = compact[-4:]
        if len(ending) < 2 or ending in seen:
            continue
        seen.append(ending)
        if len(seen) >= limit:
            break
    return seen


def build_recent_reply_ending_hint(turns: list[LlmChatTurn]) -> str:
    assistant_texts = [str(turn.content or "").strip() for turn in turns if turn.role == "assistant" and turn.content]
    if len(assistant_texts) >= 3:
        kaomoji_count = sum(1 for text in assistant_texts[-3:] if has_kaomoji_suffix(text))
        if kaomoji_count >= 2:
            return ""
    endings = recent_assistant_endings(turns)
    if not endings:
        return ""
    return "\n【收尾变化参考】这轮可优先试试这些自然收口：" + "、".join(endings) + "。"


def build_recent_reply_variation_hint(turns: list[LlmChatTurn]) -> str:
    assistant_texts = [str(turn.content or "").strip() for turn in turns if turn.role == "assistant" and turn.content]
    if not assistant_texts:
        return ""

    hints: list[str] = []
    openers = repeated_assistant_openers(turns)
    if openers:
        hints.append("最近几轮别再用这些开头：" + "、".join(openers))
        try:
            from pallas.product.persona.affect_kernel import (
                build_persona_affect_contract,
                build_variation_hint_from_contract,
            )

            affect_hint = build_variation_hint_from_contract(
                build_persona_affect_contract(repeated_openers=openers),
            )
            if affect_hint and affect_hint not in hints:
                hints.append(affect_hint.removeprefix("【开头去重】"))
        except Exception:
            pass

    recent = assistant_texts[-3:]
    animal_openers = sum(1 for text in recent if _ANIMAL_OPENER_RE.match(text))
    if animal_openers >= 2:
        hints.append("最近开头动物口癖太多，别再用哞~/喵~ 起手")

    kaomoji_count = sum(1 for text in recent if has_kaomoji_suffix(text))
    if kaomoji_count >= 2:
        hints.append("最近句尾颜文字太像模板，这轮别加 (*…*) 这类 ASCII 表情")

    recent_lengths = [len(text) for text in assistant_texts[-3:]]
    if recent_lengths and min(recent_lengths) >= 28:
        hints.append("最近解释偏满，这轮优先短一点，像顺手接一句")
    elif len(assistant_texts) >= 3:
        structural_texts = assistant_texts[-3:]
        if min(len(text) for text in structural_texts) >= 14:
            shared_markers = sum(
                1 for marker in _STRUCTURE_MARKERS if sum(1 for text in structural_texts if marker in text) >= 2
            )
            if shared_markers >= 3:
                hints.append("最近解释偏满，这轮优先短一点，像顺手接一句")

    if len(assistant_texts) >= 3:
        structural_texts = assistant_texts[-3:]
        shared_markers = [
            marker for marker in _STRUCTURE_MARKERS if sum(1 for text in structural_texts if marker in text) >= 2
        ]
        if len(shared_markers) >= 4:
            hints.append("最近句式有点一个模子，少用“先判断一下、再补解释”的答法")

    endings = [text[-1] for text in assistant_texts[-3:] if text]
    if len(endings) >= 3 and len(set(endings)) == 1:
        hints.append("最近收尾太像模板，换个自然收口")

    if not hints:
        return ""
    return "【本轮表达去重】\n- " + "\n- ".join(hints[:4])


def build_variation_hint_from_recent_texts(recent_texts: list[str]) -> str:
    texts = [str(item or "").strip() for item in recent_texts if str(item or "").strip()]
    if not texts:
        return ""

    hints: list[str] = []
    openers: list[str] = []
    for text in reversed(texts[-6:]):
        opener = classify_repeated_opener(text)
        if opener and opener not in openers:
            openers.append(opener)
        if len(openers) >= 3:
            break
    if openers:
        hints.append("最近几轮别再用这些开头：" + "、".join(openers))

    recent = texts[-3:]
    animal_openers = sum(1 for text in recent if _ANIMAL_OPENER_RE.match(text))
    if animal_openers >= 2:
        hints.append("最近开头动物口癖太多，别再用哞~/喵~ 起手")

    kaomoji_count = sum(1 for text in recent if has_kaomoji_suffix(text))
    if kaomoji_count >= 2:
        hints.append("最近句尾颜文字太像模板，这轮别加 (*…*) 这类 ASCII 表情")

    if recent and min(len(text) for text in recent) >= 28:
        hints.append("最近解释偏满，这轮优先短一点，像顺手接一句")

    endings = [text[-1] for text in recent if text]
    if len(endings) >= 3 and len(set(endings)) == 1:
        hints.append("最近收尾太像模板，换个自然收口")

    if not hints:
        return ""
    return "【本轮表达去重】\n- " + "\n- ".join(hints[:4])
