"""系统提示与上游错误正文解析"""

import json
import re

PALLAS_VAGUE_REPLY = "呃......咳嗯，下次不能喝、喝这么多了......"


def extract_upstream_error_message(body: str) -> str | None:
    """解析 HTTP 响应体中的上游错误文案"""
    try:
        data = json.loads(body)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    err = data.get("error")
    if isinstance(err, str) and err.strip():
        return err.strip()
    if isinstance(err, dict):
        m = err.get("message")
        if isinstance(m, str) and m.strip():
            return m.strip()
    return None


def sanitize_user_visible_message(text: str) -> str:
    """去掉上游 message 末尾 traceid 括号段及尾部空白。"""
    if not text:
        return text
    s = text.strip()
    parts = re.split(r"\s*[（(]\s*traceid\s*:", s, maxsplit=1, flags=re.IGNORECASE)
    out = parts[0].strip() if parts else s
    return out or s


def user_failure_reply(body_or_empty: str) -> str:
    """失败时：能解析上游 msg 则返回该文案，否则兜底句。"""
    if not body_or_empty:
        return PALLAS_VAGUE_REPLY
    msg = extract_upstream_error_message(body_or_empty)
    if not msg:
        return PALLAS_VAGUE_REPLY
    return sanitize_user_visible_message(msg) or PALLAS_VAGUE_REPLY
