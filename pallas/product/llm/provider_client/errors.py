"""Provider 错误类型 / 文案格式化与失败分类。"""

from __future__ import annotations

from urllib.parse import urlparse

import httpx

from pallas.product.llm import provider_client as _repo


class LlmProviderError(Exception):
    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


# 同 Provider 内换下一把密钥；400 等业务错误不换
API_KEY_FAILOVER_STATUSES = frozenset({401, 403, 429, 502, 503})


def should_failover_api_key(exc: BaseException) -> bool:
    return isinstance(exc, LlmProviderError) and exc.status in API_KEY_FAILOVER_STATUSES


def _provider_failure_class(exc: BaseException) -> str:
    if isinstance(exc, LlmProviderError) and exc.status is not None:
        return f"http_{exc.status}"
    if isinstance(exc, TimeoutError):
        return "timeout"
    return "provider_error"


def _emit_provider_attempt(
    *,
    telemetry_context: dict[str, str] | None,
    decision: str,
    reason: str,
    provider: str,
    model: str,
    request_method: str,
    attempt: int,
    latency_ms: int,
    failure_class: str | None = None,
) -> None:
    context = telemetry_context if isinstance(telemetry_context, dict) else {}
    turn_id = str(context.get("turn_id") or "").strip()
    if not turn_id:
        return
    try:
        _repo.record_turn_event(
            turn_id=turn_id,
            stage="provider",
            decision=decision,
            reason=reason,
            text="",
            request_id=context.get("request_id"),
            provider=provider,
            model=model,
            request_method=request_method,
            attempt=attempt,
            latency_ms=latency_ms,
            failure_class=failure_class,
        )
    except Exception:
        pass


def mask_api_key_hint(key: str) -> str:
    text = str(key or "").strip()
    if len(text) <= 9:
        return "****"
    return f"{text[:6]}*****{text[-3:]}"


def host_from_url(url: str) -> str:
    raw = str(url or "").strip()
    if not raw:
        return ""
    try:
        host = (urlparse(raw).hostname or "").strip()
    except Exception:
        return ""
    return host


def format_provider_http_error(status: int, body: str = "", *, limit: int = 200) -> str:
    """统一 HTTP 错误文案，保留 524 等状态码与短正文。"""
    detail = " ".join(str(body or "").split())
    if len(detail) > limit:
        detail = detail[: limit - 1] + "…"
    if detail:
        return f"HTTP {int(status)}: {detail}"
    return f"HTTP {int(status)}"


def format_provider_transport_error(exc: BaseException, *, url: str = "") -> str:
    """传输层失败：类型名 + host，避免 toast 只剩含糊「不可达」。"""
    host = host_from_url(url)
    name = type(exc).__name__
    if isinstance(exc, httpx.TimeoutException):
        label = "连接超时" if "Connect" in name else "请求超时"
    elif isinstance(exc, httpx.ConnectError):
        label = "连接失败"
    elif isinstance(exc, httpx.HTTPError):
        label = "网络错误"
    else:
        label = name or "请求失败"
    brief = " ".join(str(exc).split())
    if len(brief) > 160:
        brief = brief[:159] + "…"
    parts = [label]
    if host:
        parts.append(host)
    if brief and brief.lower() not in {label.lower(), name.lower()}:
        parts.append(brief)
    return " · ".join(parts)


def raise_provider_http_error(response: httpx.Response) -> None:
    raise LlmProviderError(
        format_provider_http_error(response.status_code, response.text or ""),
        status=response.status_code,
    ) from None
