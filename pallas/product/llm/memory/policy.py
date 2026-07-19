"""群内旧事（episode_notes）准入与归一化策略。"""

from __future__ import annotations

from pallas.product.persona.prompt_guard import sanitize_prompt_block

_EPISODE_NOTE_KIND = "episode_note"
_MIN_VALUE_LEN = 4
_REJECT_SUBSTRINGS = ("今天烦", "好烦", "烦死", "不开心", "难受", "emo")
_MEMORY_INSTRUCTION_RE = (
    "以后叫",
    "今后叫",
    "以后说",
    "今后说",
    "以后回复",
    "今后回复",
    "以后",
    "今后",
    "扮演",
    "忽略之前",
    "无视之前",
    "系统提示",
    "提示词",
)


def strip_teach_prefix(text: str) -> str:
    raw = (text or "").strip()
    for prefix in ("记住：", "记住:", "请你记住", "要记住", "帮我记住"):
        if raw.startswith(prefix):
            return raw[len(prefix) :].strip()
    return raw


def episode_note_has_group_value(text: str) -> bool:
    body = strip_teach_prefix(text)
    if len(body) < _MIN_VALUE_LEN:
        return False
    lowered = body.lower()
    if any(token in body for token in _REJECT_SUBSTRINGS):
        return False
    if any(token in body for token in _MEMORY_INSTRUCTION_RE):
        return False
    if body.startswith("我") and len(body) <= 6:
        return False
    if lowered in {"记一下", "这个", "那个"}:
        return False
    return True


def classify_memory_candidate(text: str) -> str | None:
    body = strip_teach_prefix(text)
    if body == "这个梗":
        return _EPISODE_NOTE_KIND
    if not episode_note_has_group_value(text):
        return None
    return _EPISODE_NOTE_KIND


def normalize_episode_note(text: str, *, max_len: int) -> str:
    body = sanitize_prompt_block(strip_teach_prefix(text), max_len=max_len).strip()
    return body.rstrip("。！？!?；;，,、").strip()
