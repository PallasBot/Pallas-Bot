"""群聊发言感知：别名提及强制进闲聊，以及轻量 ambient 插嘴。"""

from __future__ import annotations

import random
import re
import time
from dataclasses import dataclass
from threading import Lock
from typing import TYPE_CHECKING

from packages.repeater.opportunity_gate import looks_like_reply_cue
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
    rng: random.Random | None = None,
    now: float | None = None,
    record_ambient: bool = True,
) -> SpeakDecision:
    """判定是否应进入 llm_chat。

    优先级：to_me → 挡命令/旁观 → 别名提及 → ambient（cue/必要性 + 冷却 + 概率）。
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
