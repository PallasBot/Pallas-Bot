from __future__ import annotations

import re

# 日志里超长 base64 会撑爆行宽，折叠便于阅读
_BASE64_RE = re.compile(r"base64://[A-Za-z0-9+/=\s]{80,}", re.IGNORECASE)


def scrub_intercept_log_preview(plain_text: str, raw_message: str = "", *, limit: int = 48) -> str:
    """拦截日志用预览：优先纯文本；为空时用 CQ 原文（截断、折叠长 base64）。"""
    s = (plain_text or "").replace("\n", " ").strip()
    if not s:
        s = (raw_message or "").replace("\n", " ").strip()
        s = _BASE64_RE.sub("base64://…", s)
    if not s:
        return "[无纯文本且无 CQ 原文]"
    if len(s) > limit:
        return f"{s[:limit]}…"
    return s
