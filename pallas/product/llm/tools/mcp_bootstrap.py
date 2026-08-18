"""将 MCP server 的工具注册进 LLM ToolRegistry（stdio/HTTP 常驻 session）。"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from nonebot import logger

from pallas.product.llm.config import LlmMcpServerConfig, get_llm_config
from pallas.product.llm.tools.contracts import ToolCapability
from pallas.product.llm.tools.registry import LlmToolSource, LlmToolSpec, register_tool

_MCP_TOOL_NAMES: set[str] = set()
_MCP_REGISTER_ERRORS: list[dict[str, str]] = []
_SESSION_POOL_LOCK = threading.Lock()
_SESSIONS: dict[str, Any] = {}


def clear_mcp_tools() -> None:
    _MCP_TOOL_NAMES.clear()
    _MCP_REGISTER_ERRORS.clear()
    close_all_mcp_sessions()


def close_all_mcp_sessions() -> None:
    with _SESSION_POOL_LOCK:
        sessions = list(_SESSIONS.values())
        _SESSIONS.clear()
    for session in sessions:
        try:
            session.close()
        except Exception as err:
            logger.debug("MCP session close failed for ID [{}]: [{}]", session.server_id, err)


def mcp_registration_snapshot() -> dict[str, Any]:
    cfg = get_llm_config()
    servers = [
        {
            "id": server.id,
            "transport": (server.transport or "stdio").strip().lower() or "stdio",
            "command": list(server.command or []),
            "url": str(server.url or "").strip(),
            "enabled_tools": list(server.enabled_tools or []),
        }
        for server in cfg.mcp_servers
    ]
    with _SESSION_POOL_LOCK:
        live = [
            {
                "id": session.server_id,
                "transport": session.transport,
                "alive": session.alive(),
                "calls": session.call_count,
            }
            for session in _SESSIONS.values()
        ]
    return {
        "servers": servers,
        "registered_tool_names": sorted(_MCP_TOOL_NAMES),
        "registered_count": len(_MCP_TOOL_NAMES),
        "errors": list(_MCP_REGISTER_ERRORS),
        "sessions": live,
    }


def _tool_capabilities(tool_row: dict[str, Any]) -> frozenset[str]:
    annotations = tool_row.get("annotations")
    read_only = isinstance(annotations, dict) and bool(annotations.get("readOnlyHint"))
    if read_only:
        return frozenset({ToolCapability.READ_ONLY.value})
    return frozenset({ToolCapability.SIDE_EFFECTING.value})


def _tool_description(tool_row: dict[str, Any], *, server_id: str) -> str:
    description = str(tool_row.get("description") or "").strip()
    if description:
        return f"{description}（MCP: {server_id}）"
    return f"MCP 工具（server: {server_id}）"


def _tool_parameters(tool_row: dict[str, Any]) -> dict[str, Any]:
    schema = tool_row.get("inputSchema")
    if isinstance(schema, dict):
        return schema
    return {"type": "object", "properties": {}}


def _server_domains(server: LlmMcpServerConfig) -> frozenset[str]:
    return frozenset({"mcp", server.id})


def _tool_name(server_id: str, tool_row: dict[str, Any]) -> str:
    base_name = str(tool_row.get("name") or "").strip()
    return f"mcp.{server_id}.{base_name}"


def _server_fingerprint(server: LlmMcpServerConfig) -> str:
    transport = (server.transport or "stdio").strip().lower() or "stdio"
    if transport in ("http", "sse"):
        return f"http|{str(server.url or '').strip()}"
    return "stdio|" + json.dumps(list(server.command or []), ensure_ascii=False)


def _mcp_http_allowed(url: str) -> bool:
    from pallas.core.foundation.config.repo_settings import repo_env_raw_value

    allow = str(repo_env_raw_value("LLM_MCP_HTTP_ALLOWLIST") or "").strip()
    if not allow:
        return False
    allowed = {item.strip().rstrip("/") for item in allow.split(",") if item.strip()}
    normalized = url.strip().rstrip("/")
    return any(normalized.startswith(prefix) for prefix in allowed)


@dataclass
class _McpSessionBase:
    server_id: str
    transport: str
    fingerprint: str
    call_count: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)
    _next_id: int = 1

    def next_req_id(self) -> int:
        req_id = self._next_id
        self._next_id += 1
        return req_id

    def alive(self) -> bool:
        raise NotImplementedError

    def matches(self, server: LlmMcpServerConfig) -> bool:
        return self.fingerprint == _server_fingerprint(server)

    def call(self, *, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError


@dataclass
class _StdioMcpSession(_McpSessionBase):
    proc: subprocess.Popen[str] | None = None

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def ensure_started(self, server: LlmMcpServerConfig) -> None:
        if self.alive():
            return
        if not server.command:
            raise RuntimeError(f"mcp server {server.id} missing command")
        popen_kwargs: dict[str, Any] = {
            "args": list(server.command),
            "stdin": subprocess.PIPE,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
            "bufsize": 1,
        }
        if sys.platform == "win32":
            # 避免 MCP stdio 子进程弹出控制台窗口
            popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        proc = subprocess.Popen(**popen_kwargs)  # noqa: S603
        if proc.stdin is None or proc.stdout is None:
            proc.terminate()
            raise RuntimeError(f"mcp server {server.id} missing stdio pipe")

        def drain_stderr() -> None:
            if proc.stderr is None:
                return
            for _line in proc.stderr:
                continue

        threading.Thread(target=drain_stderr, daemon=True).start()
        self.proc = proc
        self._next_id = 1
        self._initialize()
        logger.info("MCP stdio session started for ID [{}]", self.server_id)

    def _read_json_line(self) -> dict[str, Any]:
        proc = self.proc
        if proc is None or proc.stdout is None:
            raise RuntimeError("mcp stdio not started")
        deadline = time.monotonic() + 60.0
        while time.monotonic() < deadline:
            line = proc.stdout.readline()
            if not line:
                raise RuntimeError("mcp stdout closed")
            line = line.strip()
            if not line:
                continue
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                # npm / uvx 启动横幅等非 JSON 行
                continue
        raise RuntimeError("mcp stdout timeout waiting for json")

    def _send_json_line(self, payload: dict[str, Any]) -> None:
        proc = self.proc
        if proc is None or proc.stdin is None:
            raise RuntimeError("mcp stdio not started")
        proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        proc.stdin.flush()

    def _call_jsonrpc(
        self,
        *,
        req_id: int,
        method: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"jsonrpc": "2.0", "id": req_id, "method": method}
        if params is not None:
            payload["params"] = params
        self._send_json_line(payload)
        while True:
            response = self._read_json_line()
            if response.get("id") == req_id:
                return response

    def _initialize(self) -> None:
        self._call_jsonrpc(
            req_id=self.next_req_id(),
            method="initialize",
            params={
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "pallas-llm-mcp", "version": "1.0"},
            },
        )
        self._send_json_line({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def call(self, *, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        with self.lock:
            if not self.alive():
                raise RuntimeError(f"mcp stdio session dead: {self.server_id}")
            response = self._call_jsonrpc(req_id=self.next_req_id(), method=method, params=params)
            self.call_count += 1
            if "error" in response:
                error = response["error"]
                if isinstance(error, dict):
                    raise RuntimeError(str(error.get("message") or "mcp call failed"))
                raise RuntimeError(str(error))
            result = response.get("result")
            return result if isinstance(result, dict) else {}

    def close(self) -> None:
        proc = self.proc
        self.proc = None
        if proc is None:
            return
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


@dataclass
class _HttpMcpSession(_McpSessionBase):
    url: str = ""
    client: Any = None

    def alive(self) -> bool:
        return self.client is not None and bool(self.url)

    def ensure_started(self, server: LlmMcpServerConfig) -> None:
        import httpx

        url = str(server.url or "").strip()
        if not url:
            raise RuntimeError(f"mcp server {server.id} missing url")
        if not _mcp_http_allowed(url):
            raise RuntimeError(f"mcp http url not in LLM_MCP_HTTP_ALLOWLIST: {url}")
        if self.alive() and self.url == url:
            return
        self.close()
        self.url = url
        self.client = httpx.Client(timeout=30.0)
        self._next_id = 1
        logger.info("MCP HTTP session for ID [{}] is ready at URL [{}]", self.server_id, url)

    def call(self, *, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        with self.lock:
            if not self.alive():
                raise RuntimeError(f"mcp http session dead: {self.server_id}")
            payload: dict[str, Any] = {"jsonrpc": "2.0", "id": self.next_req_id(), "method": method}
            if params is not None:
                payload["params"] = params
            response = self.client.post(self.url, json=payload)
            response.raise_for_status()
            body = response.json()
            self.call_count += 1
            if not isinstance(body, dict):
                raise RuntimeError("invalid mcp http response")
            error = body.get("error")
            if isinstance(error, dict):
                raise RuntimeError(str(error.get("message") or "mcp call failed"))
            result = body.get("result")
            return result if isinstance(result, dict) else {}

    def close(self) -> None:
        client = self.client
        self.client = None
        self.url = ""
        if client is None:
            return
        try:
            client.close()
        except Exception:
            pass


def _new_session(server: LlmMcpServerConfig) -> _McpSessionBase:
    transport = (server.transport or "stdio").strip().lower() or "stdio"
    fingerprint = _server_fingerprint(server)
    if transport in ("http", "sse"):
        http_session = _HttpMcpSession(
            server_id=server.id,
            transport="http",
            fingerprint=fingerprint,
        )
        http_session.ensure_started(server)
        return http_session
    stdio_session = _StdioMcpSession(
        server_id=server.id,
        transport="stdio",
        fingerprint=fingerprint,
    )
    stdio_session.ensure_started(server)
    return stdio_session


def get_or_create_mcp_session(server: LlmMcpServerConfig) -> _McpSessionBase:
    server_id = str(server.id or "").strip()
    if not server_id:
        raise RuntimeError("mcp server missing id")
    with _SESSION_POOL_LOCK:
        existing = _SESSIONS.get(server_id)
        if existing is not None and existing.matches(server) and existing.alive():
            return existing
        if existing is not None:
            _SESSIONS.pop(server_id, None)
        else:
            existing = None
    if existing is not None:
        try:
            existing.close()
        except Exception:
            pass
    session = _new_session(server)
    with _SESSION_POOL_LOCK:
        old = _SESSIONS.get(server_id)
        if old is not None and old.matches(server) and old.alive():
            try:
                session.close()
            except Exception:
                pass
            return old
        if old is not None:
            try:
                old.close()
            except Exception:
                pass
        _SESSIONS[server_id] = session
        return session


def _call_mcp_http(server: LlmMcpServerConfig, *, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """兼容旧测试与一次性探测：走常驻 HTTP session。"""
    session = get_or_create_mcp_session(server)
    return session.call(method=method, params=params)


def _call_mcp_method(
    server: LlmMcpServerConfig,
    *,
    method: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        session = get_or_create_mcp_session(server)
        return session.call(method=method, params=params)
    except Exception:
        with _SESSION_POOL_LOCK:
            stale = _SESSIONS.pop(str(server.id or "").strip(), None)
        if stale is not None:
            try:
                stale.close()
            except Exception:
                pass
        session = get_or_create_mcp_session(server)
        return session.call(method=method, params=params)


def list_mcp_tools(server: LlmMcpServerConfig) -> list[dict[str, Any]]:
    cursor: str | None = None
    tools: list[dict[str, Any]] = []
    while True:
        params = {"cursor": cursor} if cursor else {}
        result = _call_mcp_method(server, method="tools/list", params=params)
        page = result.get("tools")
        if isinstance(page, list):
            tools.extend(item for item in page if isinstance(item, dict))
        cursor = str(result.get("nextCursor") or "").strip() or None
        if cursor is None:
            break
    if server.enabled_tools:
        allowed = {item.strip() for item in server.enabled_tools if item.strip()}
        return [tool for tool in tools if str(tool.get("name") or "").strip() in allowed]
    return tools


def call_mcp_tool(server: LlmMcpServerConfig, *, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    result = _call_mcp_method(
        server,
        method="tools/call",
        params={"name": tool_name, "arguments": arguments},
    )
    return {
        "content": result.get("content"),
        "structured_content": result.get("structuredContent"),
        "is_error": bool(result.get("isError")),
    }


async def execute_mcp_tool_async(spec: LlmToolSpec, arguments: dict[str, Any]) -> dict[str, Any]:
    server_id = str(spec.mcp_server_id or "").strip()
    if not server_id:
        return {"ok": False, "error": "missing_mcp_server_id"}
    for server in get_llm_config().mcp_servers:
        if server.id == server_id:
            tool_name = spec.name.removeprefix(f"mcp.{server_id}.")
            result = await asyncio.to_thread(
                call_mcp_tool,
                server,
                tool_name=tool_name,
                arguments=arguments,
            )
            if result.get("is_error"):
                return {"ok": False, "error": json.dumps(result, ensure_ascii=False)}
            return {"ok": True, "result": result}
    return {"ok": False, "error": f"unknown_mcp_server: {server_id}"}


def build_mcp_tool_spec(server: LlmMcpServerConfig, tool_row: dict[str, Any]) -> LlmToolSpec:
    return LlmToolSpec(
        name=_tool_name(server.id, tool_row),
        description=_tool_description(tool_row, server_id=server.id),
        parameters=_tool_parameters(tool_row),
        domains=_server_domains(server),
        handler=lambda *_args, **_kwargs: {"ok": False, "error": "mcp tool should use execute branch"},
        source=LlmToolSource.MCP,
        provider_name="mcp",
        capabilities=_tool_capabilities(tool_row),
        mcp_server_id=server.id,
    )


def register_mcp_tools() -> int:
    count = 0
    _MCP_REGISTER_ERRORS.clear()
    close_all_mcp_sessions()
    for server in get_llm_config().mcp_servers:
        server_id = str(server.id or "").strip()
        if not server_id:
            _MCP_REGISTER_ERRORS.append({"server_id": "", "error": "missing_server_id"})
            continue
        try:
            tools = list_mcp_tools(server)
        except Exception as err:
            msg = str(err).strip() or err.__class__.__name__
            logger.warning("MCP registration failed for server ID [{}]: [{}]", server_id, msg)
            _MCP_REGISTER_ERRORS.append({"server_id": server_id, "error": msg})
            continue
        for tool_row in tools:
            name = _tool_name(server.id, tool_row)
            if name in _MCP_TOOL_NAMES:
                continue
            register_tool(build_mcp_tool_spec(server, tool_row))
            _MCP_TOOL_NAMES.add(name)
            count += 1
    return count
