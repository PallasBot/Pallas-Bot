"""群聊发言感知：别名提及强制进闲聊，以及轻量 ambient 插嘴。"""

from __future__ import annotations

import random
import re
import time
from collections import deque
from dataclasses import dataclass
from threading import Lock
from typing import TYPE_CHECKING

from pallas.product.llm.reply_necessity import (
    is_bystander_plain_text,
    is_noise_fragment,
    looks_like_spam_or_promo,
    score_reply_necessity,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

_CQ_AT_RE = re.compile(r"\[CQ:at,qq=\d+[^\]]*\]", re.IGNORECASE)
_AT_PLAIN_RE = re.compile(r"@[^\s@，,。！!？?：:;；]{1,24}")
_REPLY_MARK_RE = re.compile(r"\[回复[^\]]*\]")
_COMMAND_START_RE = re.compile(r"^[/!！#＃.]")
_GENERIC_ALIAS_PREFIX_CUES = ("叫", "喊", "问", "找", "戳", "cue", "艾特")
_REPLY_CUE_TOKENS = (
    "?",
    "？",
    "!",
    "！",
    "吗",
    "呢",
    "吧",
    "真的假的",
    "真假的",
    "笑死",
    "离谱",
    "怎么个事",
)

_ambient_lock = Lock()
_last_ambient_at: dict[int, float] = {}
_ambient_budget_at: dict[tuple[int, int], deque[float]] = {}


@dataclass(frozen=True, slots=True)
class SpeakDecision:
    should_speak: bool
    reason: str
    score: int = 0


def clear_speak_perception_state() -> None:
    with _ambient_lock:
        _last_ambient_at.clear()
        _ambient_budget_at.clear()


def strip_mention_noise(text: str) -> str:
    out = str(text or "")
    out = _CQ_AT_RE.sub(" ", out)
    out = _AT_PLAIN_RE.sub(" ", out)
    out = _REPLY_MARK_RE.sub(" ", out)
    return " ".join(out.split()).strip()


def _is_cjk_or_alnum(char: str) -> bool:
    if not char:
        return False
    codepoint = ord(char)
    if (
        0x4E00 <= codepoint <= 0x9FFF
        or 0x3400 <= codepoint <= 0x4DBF
        or 0x20000 <= codepoint <= 0x2A6DF
        or 0x2A700 <= codepoint <= 0x2B73F
        or 0x2B740 <= codepoint <= 0x2B81F
        or 0x2B820 <= codepoint <= 0x2CEAF
        or 0xF900 <= codepoint <= 0xFAFF
    ):
        return True
    return char.isalnum()


def _generic_alias_before_ok(content: str, start: int) -> bool:
    """通称只卡前界：挡住「漂亮牛牛」；句首/标点后的「牛牛放一首…」一律放行。"""
    if start == 0:
        return True
    prev = content[start - 1]
    if not _is_cjk_or_alnum(prev):
        return True
    prefix = content[max(0, start - 2) : start]
    return any(prefix.endswith(token) for token in _GENERIC_ALIAS_PREFIX_CUES)


def _contains_generic_alias(content: str, alias: str) -> bool:
    alias_text = str(alias or "").strip()
    if not content or not alias_text:
        return False
    alias_folded = alias_text.casefold()
    alias_len = len(alias_text)
    max_start = len(content) - alias_len
    for start in range(max_start + 1):
        segment = content[start : start + alias_len]
        if segment != alias_text and segment.casefold() != alias_folded:
            continue
        if _generic_alias_before_ok(content, start):
            return True
    return False


def text_mentions_aliases(
    text: str,
    aliases: Sequence[str],
    *,
    min_alias_len: int = 2,
    generic_aliases: Sequence[str] | None = None,
) -> bool:
    content = strip_mention_noise(text)
    if not content:
        return False
    folded = content.casefold()
    generic_casefolds = {
        str(alias or "").strip().casefold() for alias in (generic_aliases or ()) if str(alias or "").strip()
    }
    for alias in sorted((str(a or "").strip() for a in aliases), key=len, reverse=True):
        if len(alias) < int(min_alias_len):
            continue
        if alias.casefold() in generic_casefolds:
            if _contains_generic_alias(content, alias):
                return True
            continue
        if alias.casefold() in folded or alias in content:
            return True
    return False


def looks_like_bot_command(text: str) -> bool:
    plain = str(text or "").strip()
    if not plain:
        return False
    if _COMMAND_START_RE.match(plain):
        return True
    try:
        from pallas.core.foundation.command_prefix import strip_leading_command_marks

        stripped = strip_leading_command_marks(plain)
    except Exception:
        stripped = plain
    if stripped != plain and stripped:
        head = stripped.split(None, 1)[0] if stripped else ""
        if 1 <= len(head) <= 16 and head.isascii() and head.isalnum():
            return True
    return False


def looks_like_reply_cue(plain_text: str) -> bool:
    """轻量接话线索（本地副本，避免加载路径依赖 packages.repeater）。"""
    plain = str(plain_text or "").strip()
    if not plain:
        return False
    if any(token in plain for token in _REPLY_CUE_TOKENS):
        return True
    if 2 <= len(plain) <= 6 and plain.endswith(("确实", "离谱", "笑死")):
        return True
    if len(plain) <= 10 and plain.startswith(("这也", "这就", "怎么", "咋", "什么")):
        return True
    return False


def _ambient_cooldown_ok(group_id: int | None, *, cooldown_sec: int, now: float) -> bool:
    if group_id is None or int(cooldown_sec) <= 0:
        return True
    with _ambient_lock:
        last = _last_ambient_at.get(int(group_id))
    if last is None:
        return True
    return (now - last) >= float(cooldown_sec)


def _ambient_budget_available(
    bot_id: int | None,
    group_id: int | None,
    *,
    limit: int,
    window_sec: int,
    now: float,
) -> bool:
    if bot_id is None or group_id is None or int(limit) <= 0:
        return True
    key = (int(bot_id), int(group_id))
    cutoff = now - max(1, int(window_sec))
    with _ambient_lock:
        entries = _ambient_budget_at.setdefault(key, deque())
        while entries and entries[0] <= cutoff:
            entries.popleft()
        return len(entries) < int(limit)


def note_ambient_spoke(
    group_id: int | None,
    *,
    bot_id: int | None = None,
    budget_limit: int = 0,
    budget_window_sec: int = 900,
    now: float | None = None,
) -> None:
    if group_id is None:
        return
    ts = time.time() if now is None else float(now)
    with _ambient_lock:
        _last_ambient_at[int(group_id)] = ts
        if bot_id is not None and int(budget_limit) > 0:
            key = (int(bot_id), int(group_id))
            entries = _ambient_budget_at.setdefault(key, deque())
            cutoff = ts - max(1, int(budget_window_sec))
            while entries and entries[0] <= cutoff:
                entries.popleft()
            entries.append(ts)


def speak_perception_metrics(decision: SpeakDecision) -> tuple[str, ...]:
    """映射发言感知结果到 llm_task 事件名（可同时记 skip 总计与原因桶）。"""
    reason = str(decision.reason or "").strip().lower()
    if decision.should_speak:
        if reason == "mention":
            return ("speak_mention",)
        if reason == "ambient":
            return ("speak_ambient",)
        if reason == "followup":
            return ("speak_followup",)
        return ()
    detail = "speak_skip"
    if reason == "command":
        detail = "speak_skip_command"
    elif reason == "bystander":
        detail = "speak_skip_bystander"
    elif reason == "spam":
        detail = "speak_skip_spam"
    elif reason == "noise":
        detail = "speak_skip_noise"
    elif reason.startswith("ambient") or reason in {
        "ambient_off",
        "ambient_cooldown",
        "ambient_low_score",
        "ambient_miss",
        "ambient_budget",
    }:
        detail = "speak_skip_ambient"
    return ("speak_skip", detail) if detail != "speak_skip" else ("speak_skip",)


def evaluate_speak_perception(
    *,
    plain_text: str,
    aliases: Sequence[str],
    generic_aliases: Sequence[str] | None = None,
    is_to_me: bool,
    bot_id: int | None = None,
    mention_enabled: bool = True,
    ambient_enabled: bool = True,
    ambient_rate: float = 0.08,
    ambient_min_score: int = 35,
    ambient_cooldown_sec: int = 120,
    ambient_budget_limit: int = 2,
    ambient_budget_window_sec: int = 900,
    persona_speak_bias: float = 1.0,
    min_alias_len: int = 2,
    group_id: int | None = None,
    bot_recently_replied: bool = False,
    has_recent_back_and_forth: bool = False,
    followup_active: bool = False,
    rng: random.Random | None = None,
    now: float | None = None,
    record_ambient: bool = True,
) -> SpeakDecision:
    """判定是否应进入 llm_chat。

    优先级：to_me → 挡命令/旁观 → 别名提及 → 续聊软窗 → ambient。
    """
    plain = str(plain_text or "").strip()
    ts = time.time() if now is None else float(now)

    if is_to_me:
        return SpeakDecision(True, "to_me", 100)

    if looks_like_bot_command(plain):
        return SpeakDecision(False, "command", 0)

    if is_bystander_plain_text(plain, bot_id=bot_id):
        return SpeakDecision(False, "bystander", 0)

    if looks_like_spam_or_promo(plain):
        return SpeakDecision(False, "spam", 0)

    speak_generic_aliases = generic_aliases
    if speak_generic_aliases is None:
        try:
            from pallas.product.persona.self_identity import extract_generic_self_aliases

            speak_generic_aliases = extract_generic_self_aliases()
        except Exception:
            speak_generic_aliases = ()

    if mention_enabled and text_mentions_aliases(
        plain,
        aliases,
        min_alias_len=min_alias_len,
        generic_aliases=speak_generic_aliases,
    ):
        return SpeakDecision(True, "mention", 100)

    if followup_active and plain and not is_noise_fragment(plain):
        return SpeakDecision(True, "followup", 80)

    if not ambient_enabled:
        return SpeakDecision(False, "ambient_off", 0)

    if not plain or is_noise_fragment(plain):
        return SpeakDecision(False, "noise", 0)

    if not _ambient_cooldown_ok(group_id, cooldown_sec=ambient_cooldown_sec, now=ts):
        return SpeakDecision(False, "ambient_cooldown", 0)

    if not _ambient_budget_available(
        bot_id,
        group_id,
        limit=ambient_budget_limit,
        window_sec=ambient_budget_window_sec,
        now=ts,
    ):
        return SpeakDecision(False, "ambient_budget", 0)

    necessity = score_reply_necessity(
        text=plain,
        is_to_me=False,
        bot_id=bot_id,
        bot_recently_replied=bot_recently_replied,
        has_recent_back_and_forth=has_recent_back_and_forth,
        has_candidate_pool=False,
    )
    score = int(necessity.score)
    if looks_like_reply_cue(plain):
        score += 15
    bias = min(1.2, max(0.8, float(persona_speak_bias or 1.0)))
    effective_min_score = int(round(int(ambient_min_score) / bias))
    if score < effective_min_score:
        return SpeakDecision(False, "ambient_low_score", score)

    roll = (rng or random).random()
    if roll > max(0.0, min(1.0, float(ambient_rate))):
        return SpeakDecision(False, "ambient_miss", score)

    if record_ambient:
        note_ambient_spoke(
            group_id,
            bot_id=bot_id,
            budget_limit=ambient_budget_limit,
            budget_window_sec=ambient_budget_window_sec,
            now=ts,
        )
    return SpeakDecision(True, "ambient", score)
