"""AI 边界 ASGI 窄守卫：先 header 鉴权，再按实际接收字节有界，超限 413。

覆盖三条入口：AI 回调 `/callback/*`、内部任务登记 `/pallas/api/internal/ai/tasks*`、
受信工具执行 `/pallas/api/internal/llm/tools/execute`。仅做鉴权与字节边界，不建策略框架。
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

from pallas.core.platform.ai_callback import ai_bearer, internal_auth
from pallas.core.platform.ai_callback.boundary_limits import internal_json_max_bytes

_log = logging.getLogger(__name__)

_CALLBACK_PREFIX = "/callback/"
_INTERNAL_TASKS_PREFIX = "/pallas/api/internal/ai/tasks"
_TOOLS_PATH = "/pallas/api/internal/llm/tools/execute"
_MAIBOT_CONTROL_PREFIX = "/pallas/api/internal/maibot/control/"
_API_KEY_HEADER = "x-pallas-api-key"
_SINGLETON_HEADERS = (
    "authorization",
    internal_auth.INTERNAL_TOKEN_HEADER.lower(),
    _API_KEY_HEADER,
    "content-length",
)
_MAX_CONTENT_LENGTH_DIGITS = 20
_MAIBOT_CONTROL_MAX_BYTES = 2 * 1024


def _bearer_auth(headers: dict[str, str]) -> tuple[bool, int]:
    if not ai_bearer.resolve_ai_bearer_token():
        return False, 503
    if ai_bearer.verify_ai_bearer(headers.get("authorization")):
        return True, 0
    return False, 401


def _internal_auth(headers: dict[str, str]) -> tuple[bool, int]:
    if not internal_auth.derive_internal_token(internal_auth.PURPOSE_AI_TASK_REGISTRATION):
        return False, 503
    if internal_auth.verify_internal_token(
        internal_auth.PURPOSE_AI_TASK_REGISTRATION,
        headers.get(internal_auth.INTERNAL_TOKEN_HEADER.lower()),
    ):
        return True, 0
    return False, 403


def _maibot_control_auth(headers: dict[str, str]) -> tuple[bool, int]:
    purpose = internal_auth.PURPOSE_MAIBOT_CONTROL_V1
    if not internal_auth.derive_internal_token(purpose):
        return False, 503
    if internal_auth.verify_internal_token(
        purpose,
        headers.get(internal_auth.INTERNAL_TOKEN_HEADER.lower()),
    ):
        return True, 0
    return False, 403


def _tools_auth(headers: dict[str, str]) -> tuple[bool, int]:
    if headers.get("authorization") and ai_bearer.verify_ai_bearer(headers.get("authorization")):
        return True, 0
    api_key = headers.get(_API_KEY_HEADER)
    if api_key:
        from pallas.console.webui.console_login import verify_api_key

        if verify_api_key(api_key):
            return True, 0
    if not ai_bearer.resolve_ai_bearer_token():
        return False, 503
    return False, 401


def _callback_max_bytes() -> int:
    from pallas.core.platform.ai_callback.boundary_limits import callback_envelope_max_bytes

    return callback_envelope_max_bytes()


def match_rule(path: str) -> tuple[Callable[[dict[str, str]], tuple[bool, int]], Callable[[], int]] | None:
    if path.startswith(_CALLBACK_PREFIX):
        return _bearer_auth, _callback_max_bytes
    if path.startswith(_INTERNAL_TASKS_PREFIX):
        return _internal_auth, internal_json_max_bytes
    if path == _TOOLS_PATH:
        return _tools_auth, internal_json_max_bytes
    if path.startswith(_MAIBOT_CONTROL_PREFIX):
        return _maibot_control_auth, lambda: _MAIBOT_CONTROL_MAX_BYTES
    return None


async def _send_plain(send: Callable[[dict[str, Any]], Any], status: int, body: bytes) -> None:
    await send({
        "type": "http.response.start",
        "status": status,
        "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
    })
    await send({"type": "http.response.body", "body": body})


class AiBoundaryGuard:
    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[[], Any],
        send: Callable[[dict[str, Any]], Any],
    ) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        rule = match_rule(str(scope.get("path") or ""))
        if rule is None:
            await self.app(scope, receive, send)
            return
        auth, max_bytes_fn = rule
        raw_headers = [
            (key.decode("latin-1").lower(), value.decode("latin-1")) for key, value in scope.get("headers") or []
        ]
        counts = Counter(name for name, _ in raw_headers)
        # 鉴权与长度 header 重复出现即歧义（下游 Starlette 与守卫可能取不同值）→ 拒绝
        if any(counts.get(name, 0) > 1 for name in _SINGLETON_HEADERS):
            await _send_plain(send, 400, b'{"detail":"ambiguous_headers"}')
            return
        headers = dict(raw_headers)
        if headers.get("content-length") is not None and headers.get("transfer-encoding") is not None:
            await _send_plain(send, 400, b'{"detail":"ambiguous_body_length"}')
            return
        ok, status = auth(headers)
        if not ok:
            await _send_plain(send, status, b'{"detail":"unauthorized"}')
            return
        limit = max(1, int(max_bytes_fn()))
        content_length = headers.get("content-length")
        if content_length is not None:
            cl = content_length.strip()
            if not cl.isdigit():
                await _send_plain(send, 400, b'{"detail":"invalid_content_length"}')
                return
            # 超长数字串不得直接 int()（Python int 转换位数上限会抛 ValueError→500）→ 按超限处理
            if len(cl) > _MAX_CONTENT_LENGTH_DIGITS or int(cl) > limit:
                await _send_plain(send, 413, b'{"detail":"payload_too_large"}')
                return
        buffered: list[dict[str, Any]] = []
        total = 0
        too_large = False
        while True:
            message = await receive()
            buffered.append(message)
            if message.get("type") == "http.request":
                total += len(message.get("body") or b"")
                if total > limit:
                    too_large = True
                    break
                if not message.get("more_body", False):
                    break
            elif message.get("type") == "http.disconnect":
                break
        if too_large:
            await _send_plain(send, 413, b'{"detail":"payload_too_large"}')
            return
        pending = iter(buffered)

        async def replay() -> dict[str, Any]:
            try:
                return next(pending)
            except StopIteration:
                return await receive()

        await self.app(scope, replay, send)


def install_ai_boundary_guard(app: Any) -> None:
    if getattr(app.state, "_pallas_ai_boundary_guard", False):
        return
    if getattr(app, "middleware_stack", None) is not None:
        # 应用已启动：无法再加中间件。此时路由层仍有鉴权，但字节边界失效，必须显式告警。
        _log.warning("AI boundary guard not installed: app already started; byte limits inactive")
        return
    app.state._pallas_ai_boundary_guard = True
    app.add_middleware(AiBoundaryGuard)
