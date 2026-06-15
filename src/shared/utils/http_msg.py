"""系统提示与上游错误正文解析"""

import json
import re

from nonebot import logger

PALLAS_VAGUE_REPLY = "呃......咳嗯，下次不能喝、喝这么多了......"

_INTERNAL_ERROR_CODES = frozenset({
    "insufficient_user_quota",
    "insufficient_quota",
    "billing_not_active",
    "billing_hard_limit_reached",
    "payment_required",
    "account_deactivated",
})

_AUTH_ERROR_CODES = frozenset({
    "invalid_api_key",
    "authentication_error",
    "invalid_auth",
    "unauthorized",
})

_USER_VISIBLE_ERROR_CODES = frozenset({
    "content_policy_violation",
    "content_filter",
    "content_policy",
    "moderation_blocked",
    "safety_system",
    "image_generation_user_error",
    "invalid_prompt",
    "prompt_blocked",
})

_INTERNAL_MESSAGE_PATTERNS = re.compile(
    r"预扣费|剩余额度|需要预扣费|insufficient[_\s-]?quota|billing|"
    r"用户\[\d+\].*(\$|usd|余额|额度)",
    re.IGNORECASE,
)

_USER_VISIBLE_MESSAGE_PATTERNS = re.compile(
    r"违规|敏感|审核|不合规|涉黄|涉政|违法|屏蔽|禁止生成|内容政策|"
    r"content\s*policy|moderation|safety|blocked|violat|inappropriate|"
    r"not allowed|cannot generate",
    re.IGNORECASE,
)


def extract_upstream_error_message(body: str) -> str | None:
    """解析 HTTP 响应体中的上游错误文案"""
    msg, _, _ = extract_upstream_error_fields(body)
    return msg


def extract_upstream_error_fields(body: str) -> tuple[str | None, str | None, str | None]:
    """解析 error.message / error.code / error.type。"""
    try:
        data = json.loads(body)
    except Exception:
        return None, None, None
    if not isinstance(data, dict):
        return None, None, None
    err = data.get("error")
    if isinstance(err, str) and err.strip():
        return err.strip(), None, None
    if not isinstance(err, dict):
        return None, None, None
    message = err.get("message")
    code = err.get("code")
    err_type = err.get("type")
    msg = message.strip() if isinstance(message, str) and message.strip() else None
    code_s = code.strip().lower() if isinstance(code, str) and code.strip() else None
    type_s = err_type.strip().lower() if isinstance(err_type, str) and err_type.strip() else None
    return msg, code_s, type_s


def sanitize_user_visible_message(text: str) -> str:
    """去掉 traceid、request id 等调试尾巴。"""
    if not text:
        return text
    s = text.strip()
    parts = re.split(r"\s*[（(]\s*traceid\s*:", s, maxsplit=1, flags=re.IGNORECASE)
    s = parts[0].strip() if parts else s
    s = re.sub(r"\s*[（(]\s*request\s*id\s*:\s*[^）)]+[）)]", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*,?\s*request\s+id\s*:\s*\S+", "", s, flags=re.IGNORECASE)
    return s.strip() or text.strip()


def upstream_error_is_internal(message: str, code: str | None, err_type: str | None) -> bool:
    if code and code in _INTERNAL_ERROR_CODES:
        return True
    if err_type and err_type in _INTERNAL_ERROR_CODES:
        return True
    return bool(_INTERNAL_MESSAGE_PATTERNS.search(message))


def upstream_error_is_user_visible(message: str, code: str | None, err_type: str | None) -> bool:
    if code and code in _USER_VISIBLE_ERROR_CODES:
        return True
    if err_type and err_type in _USER_VISIBLE_ERROR_CODES:
        return True
    return bool(_USER_VISIBLE_MESSAGE_PATTERNS.search(message))


def upstream_error_should_skip_backend(body_or_empty: str) -> bool:
    """额度/鉴权类：换 backend，不再扫参数组合。"""
    if not body_or_empty:
        return False
    msg, code, err_type = extract_upstream_error_fields(body_or_empty)
    if not msg:
        return False
    clean = sanitize_user_visible_message(msg)
    if code and code in _AUTH_ERROR_CODES:
        return True
    return upstream_error_is_internal(clean, code, err_type)


def http_status_should_skip_backend(status: int) -> bool:
    """非 200 且不宜同 backend 继续换参数。"""
    return status in (401, 403, 429, 502, 503, 504)


def http_status_should_try_next_param(status: int) -> bool:
    """请求体/参数不被接受时换下一组参数，不换 backend。"""
    return status in (400, 415, 422)


def http_body_rejects_response_format(body: str) -> bool:
    """上游明确拒绝 response_format 参数时，不宜在同 backend 换 url/b64_json 重试。"""
    try:
        data = json.loads(body)
    except Exception:
        return False
    if not isinstance(data, dict):
        return False
    err = data.get("error")
    if not isinstance(err, dict):
        return False
    param = err.get("param")
    if isinstance(param, str) and param.strip().lower() == "response_format":
        return True
    message = err.get("message")
    if not isinstance(message, str):
        return False
    lower = message.lower()
    return "response_format" in lower and ("unknown" in lower or "unsupported" in lower)


def upstream_error_visible_to_user(body_or_empty: str) -> bool:
    """上游业务错误是否应对用户展示。"""
    if not body_or_empty:
        return False
    msg, code, err_type = extract_upstream_error_fields(body_or_empty)
    if not msg:
        return False
    clean = sanitize_user_visible_message(msg)
    if upstream_error_is_internal(clean, code, err_type):
        return False
    return upstream_error_is_user_visible(clean, code, err_type)


def user_failure_reply(body_or_empty: str, *, vague_reply: str | None = None) -> str:
    """失败回复：可展示类返回脱敏上游文案，内部/未识别类返回兜底句。"""
    fallback = vague_reply or PALLAS_VAGUE_REPLY
    if not body_or_empty:
        return fallback
    msg, code, err_type = extract_upstream_error_fields(body_or_empty)
    if not msg:
        return fallback
    clean = sanitize_user_visible_message(msg)
    if upstream_error_is_internal(clean, code, err_type):
        logger.warning(f"upstream failure (user sees vague reply): {clean} code={code!r}")
        return fallback
    if upstream_error_is_user_visible(clean, code, err_type):
        return clean or fallback
    logger.warning(f"upstream failure (unclassified, vague reply): {clean} code={code!r}")
    return fallback
