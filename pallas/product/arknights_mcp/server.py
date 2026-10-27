from __future__ import annotations

import ipaddress
import json
import math
import re
import threading
import time
from collections import OrderedDict, deque
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qsl, urlsplit

import anyio
from jsonschema import Draft202012Validator
from mcp.server import Server
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import CallToolRequestParams, CallToolResult, ListToolsResult, TextContent, Tool, ToolAnnotations

from pallas.product.arknights_mcp.auth import MAX_KEYS, SCOPES, Credential, CredentialStore

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from pathlib import Path

    from starlette.applications import Starlette
    from starlette.types import ASGIApp, Receive, Scope, Send

QUERY_TOOL_SCOPES = {
    "arknights.operator.get": "arknights:read",
    "arknights.operator.search": "arknights:read",
    "arknights.skill.get": "arknights:read",
    "arknights.enemy.get": "arknights:read",
    "arknights.enemy.search": "arknights:read",
    "prts.search": "prts:read",
    "prts.read": "prts:read",
    "prts.timeline": "prts:read",
}
SAFE_QUERY_ERRORS = frozenset({
    "unknown_tool",
    "invalid_arguments",
    "source_disabled",
    "source_unavailable",
    "query_failed",
    "output_limit_exceeded",
})
_MAX_RESULT_BYTES = 64 * 1024
_MCP_PATH = "/mcp"
_AUTHENTICATED_KEY: ContextVar[Credential | None] = ContextVar("pallas_mcp_key", default=None)
_AUTH_HEADER = re.compile(r"Bearer ([^\s]+)\Z", re.IGNORECASE)
_URL_CREDENTIAL_NAMES = frozenset({"token", "access_token", "api_key", "apikey", "authorization"})
_PRIVATE_RESULT_FIELDS = frozenset({
    "absolute_path",
    "cache_path",
    "debug_error",
    "error",
    "error_detail",
    "exception",
    "exception_detail",
    "exception_type",
    "file_name",
    "file_path",
    "filename",
    "internal_error",
    "local_path",
    "path",
    "source_path",
    "traceback",
})
_QUERY_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "ok": {"type": "boolean"},
        "error": {"type": "string"},
        "result": {"anyOf": [{"type": "object"}, {"type": "null"}]},
    },
    "required": ["ok", "error", "result"],
    "additionalProperties": False,
}


def _service() -> tuple[Mapping[str, dict[str, Any]], Callable[[str, dict[str, Any]], dict[str, Any]]]:
    from pallas.product.arknights_kb import service

    return service.QUERY_TOOLS, service.execute_query


def _is_loopback(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


def _host_with_port(host: str, port: int) -> str:
    bare_host = host.strip("[]")
    if ":" in bare_host:
        bare_host = f"[{bare_host}]"
    return f"{bare_host}:{port}"


def _validate_host(value: str) -> str:
    if not value or "*" in value or value.strip() != value or any(char.isspace() for char in value):
        raise ValueError("allowed hosts must be exact Host header values")
    parsed = urlsplit(f"//{value}")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("allowed hosts must contain a valid port") from exc
    if not parsed.hostname or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
        raise ValueError("allowed hosts must be exact Host header values")
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("allowed hosts must contain a valid port")
    return value


def _validate_origin(value: str) -> str:
    parsed = urlsplit(value)
    if (
        value == "null"
        or "*" in value
        or parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("allowed origins must be exact HTTP(S) origins")
    try:
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            raise ValueError("allowed origins must contain a valid port")
    except ValueError as exc:
        raise ValueError("allowed origins must contain a valid port") from exc
    return value


def _validate_source_url(value: str | None) -> str | None:
    if value is None:
        return None
    error = "source URL must be an absolute HTTPS URL without credentials, query, or fragment"
    if type(value) is not str or not value or value != value.strip() or any(char.isspace() for char in value):
        raise ValueError(error)
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise ValueError(error) from exc
    if (
        parsed.scheme != "https"
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or "?" in value
        or parsed.fragment
        or "#" in value
        or "\\" in parsed.netloc
        or (port is not None and not 1 <= port <= 65535)
    ):
        raise ValueError(error)
    return value


def _load_tool_specs(
    specs: Mapping[str, dict[str, Any]] | None,
    executor: Callable[[str, dict[str, Any]], dict[str, Any]] | None,
) -> tuple[dict[str, dict[str, Any]], Callable[[str, dict[str, Any]], dict[str, Any]]]:
    if specs is None and executor is None:
        specs, executor = _service()
        require_all = True
    elif specs is None or executor is None:
        raise ValueError("tool specs and executor must be provided together")
    else:
        require_all = False

    normalized = dict(specs)
    if require_all and set(normalized) != set(QUERY_TOOL_SCOPES):
        raise ValueError("the shared query service does not expose the frozen MCP tool set")
    if not normalized or set(normalized) - set(QUERY_TOOL_SCOPES):
        raise ValueError("only the frozen read-only MCP tool set can be exposed")
    for name, spec in normalized.items():
        if not isinstance(spec, dict):
            raise ValueError("invalid MCP tool metadata")
        description = spec.get("description")
        parameters = spec.get("parameters")
        scope = spec.get("scope")
        if (
            not isinstance(description, str)
            or not description.strip()
            or not isinstance(parameters, dict)
            or parameters.get("type") != "object"
            or parameters.get("additionalProperties") is not False
            or scope != QUERY_TOOL_SCOPES[name]
            or scope not in SCOPES
        ):
            raise ValueError("invalid MCP tool metadata")
        try:
            Draft202012Validator.check_schema(parameters)
        except Exception as exc:
            raise ValueError("invalid MCP tool input schema") from exc
    return normalized, executor


def _listener_allowlists(
    host: str,
    port: int,
    allow_remote: bool,
    allowed_hosts: tuple[str, ...] | list[str] | None,
    allowed_origins: tuple[str, ...] | list[str],
) -> tuple[frozenset[str], frozenset[str]]:
    remote = not _is_loopback(host)
    if remote and not allow_remote:
        raise ValueError("non-loopback binding requires --allow-remote")
    if allowed_hosts is None:
        if remote:
            raise ValueError("remote binding requires explicit allowed hosts")
        host_values = (_host_with_port(host, port),)
    else:
        host_values = tuple(allowed_hosts)
    if not host_values:
        raise ValueError("at least one allowed host is required")
    checked_hosts = frozenset(_validate_host(value) for value in host_values)
    checked_origins = frozenset(_validate_origin(value) for value in allowed_origins)
    return checked_hosts, checked_origins


def _validate_resource_limits(
    rate_limit: int,
    rate_window_seconds: int,
    concurrency: int,
    max_request_body_size: int,
) -> None:
    if not 1 <= rate_limit <= 1000 or not 1 <= rate_window_seconds <= 3600:
        raise ValueError("rate limit settings are outside the supported bounds")
    if not 1 <= concurrency <= 64 or not 1024 <= max_request_body_size <= 1024 * 1024:
        raise ValueError("request resource limits are outside the supported bounds")


def _contains_private_result_fields(value: Any) -> bool:
    if isinstance(value, dict):
        return any(
            not isinstance(key, str)
            or key.casefold() in _PRIVATE_RESULT_FIELDS
            or _contains_private_result_fields(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_private_result_fields(item) for item in value)
    return False


def _query_result(value: Any) -> dict[str, Any]:
    if (
        not isinstance(value, dict)
        or type(value.get("ok")) is not bool
        or not isinstance(value.get("error"), str)
        or (value.get("result") is not None and not isinstance(value.get("result"), dict))
    ):
        return {"ok": False, "error": "query_failed", "result": None}
    ok = value["ok"]
    error = value["error"]
    result = value["result"]
    if (ok and error) or (not ok and error not in SAFE_QUERY_ERRORS):
        return {"ok": False, "error": "query_failed", "result": None}
    if ok and result is None:
        return {"ok": False, "error": "query_failed", "result": None}
    if _contains_private_result_fields(result):
        return {"ok": False, "error": "query_failed", "result": None}

    output = {"ok": ok, "error": error, "result": result}
    try:
        encoded = json.dumps(output, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError, UnicodeError):
        return {"ok": False, "error": "query_failed", "result": None}
    if len(encoded) > _MAX_RESULT_BYTES:
        return {"ok": False, "error": "output_limit_exceeded", "result": None}
    return output


def _tool_result(value: dict[str, Any], *, is_error: bool = False) -> CallToolResult:
    return CallToolResult(content=[], structuredContent=value, isError=is_error)


async def run_sync_query(
    executor: Callable[[str, dict[str, Any]], dict[str, Any]],
    name: str,
    arguments: dict[str, Any],
    limiter: Any,
) -> dict[str, Any]:
    return await anyio.to_thread.run_sync(executor, name, arguments, limiter=limiter, abandon_on_cancel=False)


class _RequestGate:
    def __init__(self, limit: int):
        self.limit = limit
        self.active = 0
        self.lock = threading.Lock()

    def enter(self) -> bool:
        with self.lock:
            if self.active >= self.limit:
                return False
            self.active += 1
            return True

    def leave(self) -> None:
        with self.lock:
            self.active -= 1


class _KeyRateLimiter:
    def __init__(self, limit: int, window_seconds: int):
        self.limit = limit
        self.window_seconds = window_seconds
        self.entries: OrderedDict[str, deque[float]] = OrderedDict()
        self.lock = threading.Lock()

    def consume(self, key_id: str) -> tuple[bool, int]:
        now = time.monotonic()
        cutoff = now - self.window_seconds
        with self.lock:
            for existing_id in tuple(self.entries):
                entries = self.entries[existing_id]
                while entries and entries[0] <= cutoff:
                    entries.popleft()
                if not entries:
                    del self.entries[existing_id]
            entries = self.entries.setdefault(key_id, deque())
            self.entries.move_to_end(key_id)
            if len(entries) >= self.limit:
                return False, max(1, math.ceil(entries[0] + self.window_seconds - now))
            entries.append(now)
            while len(self.entries) > MAX_KEYS:
                self.entries.popitem(last=False)
            return True, 0


async def _respond(send: Send, status: int, body: str, headers: tuple[tuple[bytes, bytes], ...] = ()) -> None:
    data = body.encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": (
                (b"content-type", b"text/plain; charset=utf-8"),
                (b"content-length", str(len(data)).encode()),
                *headers,
            ),
        },
    )
    await send({"type": "http.response.body", "body": data})


def _build_tool_handlers(
    tool_specs: dict[str, dict[str, Any]],
    query_executor: Callable[[str, dict[str, Any]], dict[str, Any]],
    concurrency: int,
) -> tuple[list[Tool], Callable[..., Any], Callable[..., Any]]:
    validators = {name: Draft202012Validator(spec["parameters"]) for name, spec in tool_specs.items()}
    tools = [
        Tool(
            name=name,
            description=spec["description"],
            inputSchema=spec["parameters"],
            outputSchema=_QUERY_OUTPUT_SCHEMA,
            annotations=ToolAnnotations(
                read_only_hint=True,
                destructive_hint=False,
                idempotent_hint=True,
                open_world_hint=False,
            ),
        )
        for name, spec in tool_specs.items()
    ]
    worker_limiter = None

    async def list_tools(_ctx: Any, _params: Any) -> ListToolsResult:
        credential = _AUTHENTICATED_KEY.get()
        if credential is None:
            return ListToolsResult(tools=[])
        return ListToolsResult(tools=[tool for tool in tools if tool_specs[tool.name]["scope"] in credential.scopes])

    async def call_tool(_ctx: Any, params: CallToolRequestParams) -> CallToolResult:
        credential = _AUTHENTICATED_KEY.get()
        spec = tool_specs.get(params.name)
        if spec is None:
            return _tool_result({"ok": False, "error": "unknown_tool", "result": None}, is_error=True)
        if credential is None or spec["scope"] not in credential.scopes:
            return CallToolResult(content=[TextContent(type="text", text="insufficient_scope")], isError=True)

        arguments = params.arguments
        if not isinstance(arguments, dict) or next(validators[params.name].iter_errors(arguments), None) is not None:
            return _tool_result({"ok": False, "error": "invalid_arguments", "result": None}, is_error=True)

        nonlocal worker_limiter
        if worker_limiter is None:
            worker_limiter = anyio.CapacityLimiter(concurrency)
        try:
            raw_result = await run_sync_query(query_executor, params.name, arguments, worker_limiter)
        except Exception:
            raw_result = None
        result = _query_result(raw_result)
        return _tool_result(result, is_error=not result["ok"])

    return tools, list_tools, call_tool


class _McpRequestGuard:
    def __init__(
        self,
        app: ASGIApp,
        *,
        key_store: CredentialStore,
        allowed_hosts: frozenset[str],
        allowed_origins: frozenset[str],
        rate_limiter: _KeyRateLimiter,
        request_gate: _RequestGate,
    ):
        self.app = app
        self.key_store = key_store
        self.allowed_hosts = allowed_hosts
        self.allowed_origins = allowed_origins
        self.rate_limiter = rate_limiter
        self.request_gate = request_gate

    async def _authenticate(self, scope: Scope, send: Send) -> Credential | None:
        auth_headers = [value for name, value in scope["headers"] if name.lower() == b"authorization"]
        if len(auth_headers) != 1:
            await _respond(send, 401, "Unauthorized", ((b"www-authenticate", b"Bearer"),))
            return None
        try:
            raw_auth = auth_headers[0].decode("ascii")
        except UnicodeError:
            raw_auth = ""
        match = _AUTH_HEADER.fullmatch(raw_auth)
        secret = match.group(1) if match else ""
        try:
            credential = await anyio.to_thread.run_sync(self.key_store.authenticate, secret)
        except Exception:
            credential = None
        if credential is None:
            await _respond(send, 401, "Unauthorized", ((b"www-authenticate", b"Bearer"),))
            return None

        query = scope.get("query_string", b"")
        if len(query) > 4096:
            await _respond(send, 400, "Invalid request")
            return None
        try:
            query_items = parse_qsl(query.decode("ascii"), keep_blank_values=True)
        except (UnicodeError, ValueError):
            await _respond(send, 400, "Invalid request")
            return None
        if any(name.lower() in _URL_CREDENTIAL_NAMES for name, _ in query_items):
            await _respond(send, 400, "Credentials must use the Authorization header")
            return None
        return credential

    async def _valid_host_origin(self, scope: Scope, send: Send) -> bool:
        hosts = [value for name, value in scope["headers"] if name.lower() == b"host"]
        if len(hosts) != 1 or hosts[0].decode("latin-1") not in self.allowed_hosts:
            await _respond(send, 421, "Invalid Host")
            return False
        origins = [value for name, value in scope["headers"] if name.lower() == b"origin"]
        if len(origins) > 1 or (origins and origins[0].decode("latin-1") not in self.allowed_origins):
            await _respond(send, 403, "Invalid Origin")
            return False
        return True

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") != _MCP_PATH:
            await self.app(scope, receive, send)
            return

        if not self.request_gate.enter():
            await _respond(send, 429, "Too Many Requests", ((b"retry-after", b"1"),))
            return

        try:
            credential = await self._authenticate(scope, send)
            if credential is None:
                return
            if not await self._valid_host_origin(scope, send):
                return

            allowed, retry_after = self.rate_limiter.consume(credential.id)
            if not allowed:
                await _respond(send, 429, "Too Many Requests", ((b"retry-after", str(retry_after).encode()),))
                return

            token = _AUTHENTICATED_KEY.set(credential)
            try:
                await self.app(scope, receive, send)
            finally:
                _AUTHENTICATED_KEY.reset(token)
        finally:
            self.request_gate.leave()


def create_app(
    *,
    data_root: Path | None = None,
    specs: Mapping[str, dict[str, Any]] | None = None,
    executor: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
    host: str = "127.0.0.1",
    port: int = 8765,
    allow_remote: bool = False,
    allowed_hosts: tuple[str, ...] | list[str] | None = None,
    allowed_origins: tuple[str, ...] | list[str] = (),
    rate_limit: int = 60,
    rate_window_seconds: int = 60,
    concurrency: int = 8,
    max_request_body_size: int = 64 * 1024,
    source_url: str | None = None,
) -> Starlette:
    if not 1 <= port <= 65535:
        raise ValueError("port must be between 1 and 65535")
    source_url = _validate_source_url(source_url)
    checked_hosts, checked_origins = _listener_allowlists(host, port, allow_remote, allowed_hosts, allowed_origins)
    _validate_resource_limits(rate_limit, rate_window_seconds, concurrency, max_request_body_size)

    tool_specs, query_executor = _load_tool_specs(specs, executor)
    tools, list_tools, call_tool = _build_tool_handlers(tool_specs, query_executor, concurrency)
    key_store = CredentialStore(data_root)
    request_gate = _RequestGate(concurrency)
    rate_limiter = _KeyRateLimiter(rate_limit, rate_window_seconds)

    server = Server(
        "pallas-arknights-readonly",
        version="1.0.0",
        description="Read-only queries over local Arknights and PRTS data.",
        instructions=(f"运行版源码归档（对应当前运行代码）：{source_url}" if source_url else None),
        on_list_tools=list_tools,
        on_call_tool=call_tool,
    )
    app = server.streamable_http_app(
        streamable_http_path=_MCP_PATH,
        json_response=True,
        stateless_http=True,
        max_request_body_size=max_request_body_size,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=list(checked_hosts),
            allowed_origins=list(checked_origins),
        ),
        host=host,
    )
    app.add_middleware(
        _McpRequestGuard,
        key_store=key_store,
        allowed_hosts=checked_hosts,
        allowed_origins=checked_origins,
        rate_limiter=rate_limiter,
        request_gate=request_gate,
    )
    app.state.key_store = key_store
    app.state.request_gate = request_gate
    app.state.rate_limiter = rate_limiter
    return app
