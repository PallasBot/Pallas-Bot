"""群聊发言感知：别名提及强制进闲聊，以及轻量 ambient 插嘴。"""

from __future__ import annotations

import random
import re
import time
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


@dataclass(frozen=True, slots=True)
class SpeakDecision:
    should_speak: bool
    reason: str
    score: int = 0


def clear_speak_perception_state() -> None:
    with _ambient_lock:
        _last_ambient_at.clear()


def strip_mention_noise(text: str) -> str:
    out = str(text or "")
    out = _CQ_AT_RE.sub(" ", out)
    out = _AT_PLAIN_RE.sub(" ", out)
    out = _REPLY_MARK_RE.sub(" ", out)
    return " ".join(out.split()).strip()


def text_mentions_aliases(
    text: str,
    aliases: Sequence[str],
    *,
    min_alias_len: int = 2,
) -> bool:
    content = strip_mention_noise(text)
    if not content:
        return False
    folded = content.casefold()
    for alias in sorted((str(a or "").strip() for a in aliases), key=len, reverse=True):
        if len(alias) < int(min_alias_len):
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


def note_ambient_spoke(group_id: int | None, *, now: float | None = None) -> None:
    if group_id is None:
        return
    ts = time.time() if now is None else float(now)
    with _ambient_lock:
        _last_ambient_at[int(group_id)] = ts


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
    }:
        detail = "speak_skip_ambient"
    return ("speak_skip", detail) if detail != "speak_skip" else ("speak_skip",)


def evaluate_speak_perception(
    *,
    plain_text: str,
    aliases: Sequence[str],
    is_to_me: bool,
    bot_id: int | None = None,
    mention_enabled: bool = True,
    ambient_enabled: bool = True,
    ambient_rate: float = 0.08,
    ambient_min_score: int = 35,
    ambient_cooldown_sec: int = 120,
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

    if mention_enabled and text_mentions_aliases(plain, aliases, min_alias_len=min_alias_len):
        return SpeakDecision(True, "mention", 100)

    if followup_active and plain and not is_noise_fragment(plain):
        return SpeakDecision(True, "followup", 80)

    if not ambient_enabled:
        return SpeakDecision(False, "ambient_off", 0)

    if not plain or is_noise_fragment(plain):
        return SpeakDecision(False, "noise", 0)

    if not _ambient_cooldown_ok(group_id, cooldown_sec=ambient_cooldown_sec, now=ts):
        return SpeakDecision(False, "ambient_cooldown", 0)

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
    if score < int(ambient_min_score):
        return SpeakDecision(False, "ambient_low_score", score)

    roll = (rng or random).random()
    if roll > max(0.0, min(1.0, float(ambient_rate))):
        return SpeakDecision(False, "ambient_miss", score)

    if record_ambient:
        note_ambient_spoke(group_id, now=ts)
    return SpeakDecision(True, "ambient", score)
