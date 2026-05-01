"""将异常格式化为单行摘要（日志 / API error 字段）。"""

from __future__ import annotations

import httpx


def format_exception_for_log(exc: BaseException) -> str:
    """勿把裸 ``Exception`` 传入 loguru 的「{}」占位：部分环境下会得到空白输出。"""
    if isinstance(exc, httpx.HTTPStatusError):
        resp = exc.response
        url = str(resp.request.url)
        reason = (getattr(resp, "reason_phrase", None) or "").strip()
        head = f"{resp.status_code}"
        if reason:
            head = f"{head} {reason}"
        text = (resp.text or "").replace("\r", "").strip().replace("\n", " ")
        if len(text) > 400:
            text = text[:397] + "..."
        return f"HTTPStatusError {head} url={url}" + (f" body={text!r}" if text else "")
    if isinstance(exc, httpx.RequestError):
        url = str(exc.request.url) if exc.request is not None else ""
        suffix = f" url={url}" if url else ""
        detail = str(exc).strip() or repr(exc)
        return f"{type(exc).__name__}{suffix}: {detail}"
    msg = str(exc).strip()
    if msg:
        return f"{type(exc).__name__}: {msg}"
    return f"{type(exc).__name__}: {exc!r}"
