"""关系备注层（relationship_notes）准入、归一化与教导解析。

契约（pallas-core-contract §5）：这是高门槛层，只保存对某人/某类人的**稳定**关系
事实，不能把短期情绪误写成稳定关系。因此准入比 episode_notes 更严：
- 必须形如「对 @某人 …」或「@某人 是 …」的稳定陈述
- 拒绝明显的瞬时情绪（今天烦/好烦/不开心 等）
- 拒绝过短或无信息量的残句
"""

from __future__ import annotations

import re

from pallas.product.persona.prompt_guard import sanitize_prompt_block

_MIN_VALUE_LEN = 4
_REJECT_SUBSTRINGS = ("今天烦", "好烦", "烦死", "不开心", "难受", "emo", "心情")

_RELATION_PREFIXES = (
    "记住关系：",
    "记住关系:",
    "记住对",
    "对我来说",
)

_PRONOUN_WHO = frozenset({"你", "我", "他", "她", "它", "咱", "您", "俺", "尔", "汝", "彼", "此", "谁"})
_QUESTION_MARKERS = (
    "吗",
    "呢",
    "？",
    "?",
    "怎么",
    "为何",
    "为什么",
    "干嘛",
    "怎样",
    "如何",
    "是不是",
    "能不能",
    "会不会",
)
_STABLE_RELATION_HINTS = (
    "是",
    "为",
    "担任",
    "角色",
    "群主",
    "群管",
    "管理",
    "推",
    "老板",
    "队长",
    "朋友",
    "同事",
    "恋人",
    "师傅",
    "徒弟",
    "领导",
    "负责人",
    "领袖",
)

# 「对 <名> …」「<名> 是我推/老板/群主…」一类稳定关系陈述
_RELATION_PATTERNS = (
    re.compile(r"^对(?P<who>[^，,。\s]{1,16})[，,：:]?\s*(?P<rest>.+)$"),
    re.compile(r"^(?P<who>[^，,。\s]{1,16})是我(?P<rest>.+)$"),
)

_AT_RE = re.compile(r"\[CQ:at,qq=(?P<qq>\d+)[^\]]*\]", re.IGNORECASE)


def extract_at_target(raw: str) -> int | None:
    """从消息原文里取第一个 @ 的 QQ，作为关系备注的对象。"""
    match = _AT_RE.search(raw or "")
    if not match:
        return None
    try:
        return int(match.group("qq"))
    except (TypeError, ValueError):
        return None


def relationship_note_has_value(text: str) -> bool:
    body = (text or "").strip()
    if len(body) < _MIN_VALUE_LEN:
        return False
    if any(token in body for token in _REJECT_SUBSTRINGS):
        return False
    return True


def relationship_teach_likely(plain_text: str) -> bool:
    """廉价预筛：只有明显教导话术才进关系解析。"""
    body = (plain_text or "").strip()
    if not body:
        return False
    if any(body.startswith(prefix) for prefix in _RELATION_PREFIXES):
        return True
    if body.startswith("对") and len(body) >= 6:
        return True
    return "是我" in body and len(body) >= 6


def _has_stable_relation_hint(text: str) -> bool:
    return any(token in text for token in _STABLE_RELATION_HINTS)


def _looks_like_conversational_dui(who: str, rest: str) -> bool:
    if who in _PRONOUN_WHO:
        return True
    return any(marker in rest for marker in _QUESTION_MARKERS)


def _matches_relation_pattern(body: str) -> bool:
    for pattern in _RELATION_PATTERNS:
        matched = pattern.match(body)
        if matched is None:
            continue
        who = str(matched.group("who") or "").strip()
        rest = str(matched.group("rest") or "").strip()
        if pattern.pattern.startswith("^对"):
            if _looks_like_conversational_dui(who, rest):
                return False
            if len(who) < 2:
                return False
            if not _has_stable_relation_hint(body):
                return False
        elif who in _PRONOUN_WHO or len(who) < 2:
            return False
        return True
    return False


def resolve_relationship_teach_target_id(
    raw: str,
    *,
    speaker_id: int,
    bot_self_id: int,
) -> int:
    """教导对象：@ 他人时用被 @ 者；仅 @ bot 或无 @ 时用说话人。"""
    at_id = extract_at_target(raw)
    if at_id is not None and int(at_id) != int(bot_self_id):
        return int(at_id)
    return int(speaker_id)


def parse_relationship_teach(plain_text: str) -> str | None:
    """从「记住关系：…」「对 X 来说…」话术解析稳定关系陈述，返回归一化正文。"""
    body = (plain_text or "").strip()
    if not body or not relationship_teach_likely(body):
        return None
    for prefix in _RELATION_PREFIXES:
        if body.startswith(prefix):
            body = body[len(prefix) :].strip()
            break
    else:
        if not _matches_relation_pattern(body):
            return None
    if not relationship_note_has_value(body):
        return None
    return body


def normalize_relationship_note(text: str, *, max_len: int) -> str:
    return sanitize_prompt_block((text or "").strip(), max_len=max_len).strip()
