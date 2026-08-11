"""入站事件日志压缩：折叠长 URL / base64，避免 SUCCESS 行撑爆。"""

from __future__ import annotations

import re

_BASE64_RE = re.compile(r"base64://[A-Za-z0-9+/=\s]{80,}", re.IGNORECASE)
_DATA_URI_RE = re.compile(
    r"data:(?:image|video|audio)[^,]*,[A-Za-z0-9+/=\s]{80,}",
    re.IGNORECASE,
)
# OneBot / CQ 常见超长 url=…（含未加引号）
_URL_QUERY_RE = re.compile(
    r"(https?://[^\s'\"\]>,]{80,})",
    re.IGNORECASE,
)


def compact_inbound_event_log(text: str, *, max_len: int = 240) -> str:
    """压缩入站事件日志正文；保留前缀语义，截断媒体/URL。"""
    s = (text or "").replace("\n", " ").strip()
    if not s:
        return s
    s = _BASE64_RE.sub("base64://…", s)
    s = _DATA_URI_RE.sub("data:…", s)
    s = _URL_QUERY_RE.sub(lambda m: f"{m.group(1)[:48]}…", s)
    if len(s) > max_len:
        return f"{s[: max_len - 1]}…"
    return s


def compact_group_message_log(
    *,
    bot_id: str,
    group_id: int,
    user_id: int,
    message: str,
    max_len: int = 240,
) -> str:
    prefix = f"[Bot {bot_id:>10}] [群 {group_id:>10}] [用户 {user_id:>10}] "
    content = compact_inbound_event_log(message, max_len=max(1, max_len - len(prefix)))
    return f"{prefix}{content}"


def inbound_event_log_as_debug(event_type: str) -> bool:
    """notice / request / meta 默认 DEBUG，避免完整 dict 刷 SUCCESS。"""
    return event_type in {"notice", "request", "meta_event"}
