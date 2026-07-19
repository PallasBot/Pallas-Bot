from __future__ import annotations

_INVISIBLE_CHARS = ("\u200b", "\u200c", "\u200d", "\ufeff", "\u2060")

_APPROVE_REPLY_TEXT = frozenset({"同意", "好", "yes", "y", "ok", "留空"})
_REJECT_REPLY_TEXT = frozenset({"拒绝", "不要", "否", "no", "n"})


def normalize_approval_reply_text(text: str) -> str:
    for ch in _INVISIBLE_CHARS:
        text = text.replace(ch, "")
    return text.strip().lower()


def extract_approval_reply_text_from_body(body: str, quoted_body: str | None) -> str:
    normalized = normalize_approval_reply_text(body)
    if quoted_body is None:
        return normalized
    quoted = normalize_approval_reply_text(quoted_body)
    if normalized == quoted:
        return ""
    return normalized


def classify_approval_reply_text(text: str) -> str | None:
    normalized = normalize_approval_reply_text(text)
    if not normalized:
        return "approve"
    if normalized in _APPROVE_REPLY_TEXT:
        return "approve"
    if normalized in _REJECT_REPLY_TEXT:
        return "reject"
    return None
