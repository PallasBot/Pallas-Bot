"""将 stdio MCP server 的工具注册进 LLM ToolRegistry。"""

from __future__ import annotations

import asyncio
import json
import subprocess
import threading
from typing import Any

from pallas.product.llm.config import LlmMcpServerConfig, get_llm_config
from pallas.product.llm.tools.contracts import ToolCapability
from pallas.product.llm.tools.registry import LlmToolSource, LlmToolSpec, register_tool

_MCP_TOOL_NAMES: set[str] = set()


def clear_mcp_tools() -> None:
    _MCP_TOOL_NAMES.clear()


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


def _spawn_stdio_server(server: LlmMcpServerConfig) -> subprocess.Popen[str]:
    transport = (server.transport or "stdio").strip().lower()
    if transport not in ("stdio", ""):
        raise RuntimeError(f"use http transport helper for: {server.transport}")
    if not server.command:
        raise RuntimeError(f"mcp server {server.id} missing command")
    proc = subprocess.Popen(
        list(server.command),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    if proc.stdin is None or proc.stdout is None:
        raise RuntimeError(f"mcp server {server.id} missing stdio pipe")

    def drain_stderr() -> None:
        if proc.stderr is None:
            return
        for _line in proc.stderr:
            continue

    threading.Thread(target=drain_stderr, daemon=True).start()
    return proc


def _read_json_line(proc: subprocess.Popen[str]) -> dict[str, Any]:
    assert proc.stdout is not None
    while True:
        line = proc.stdout.readline()
        if not line:
            raise RuntimeError("mcp stdout closed")
        line = line.strip()
        if not line:
            continue
        return json.loads(line)


def _send_json_line(proc: subprocess.Popen[str], payload: dict[str, Any]) -> None:
    assert proc.stdin is not None
    proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
    proc.stdin.flush()


def _call_jsonrpc(
    proc: subprocess.Popen[str],
    *,
    req_id: int,
    method: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {"jsonrpc": "2.0", "id": req_id, "method": method}
    if params is not None:
        payload["params"] = params
    _send_json_line(proc, payload)
    while True:
        response = _read_json_line(proc)
        if response.get("id") == req_id:
            return response


def _initialize_server(proc: subprocess.Popen[str]) -> None:
    _call_jsonrpc(
        proc,
        req_id=1,
        method="initialize",
        params={
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "pallas-llm-mcp", "version": "1.0"},
        },
    )
    _send_json_line(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})


def _mcp_http_allowed(url: str) -> bool:
    from pallas.core.foundation.config.repo_settings import repo_env_raw_value

    allow = str(repo_env_raw_value("LLM_MCP_HTTP_ALLOWLIST") or "").strip()
    if not allow:
        return False
    allowed = {item.strip().rstrip("/") for item in allow.split(",") if item.strip()}
    normalized = url.strip().rstrip("/")
    return any(normalized.startswith(prefix) for prefix in allowed)


def _call_mcp_http(server: LlmMcpServerConfig, *, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    url = str(server.url or "").strip()
    if not url:
        raise RuntimeError(f"mcp server {server.id} missing url")
    if not _mcp_http_allowed(url):
        raise RuntimeError(f"mcp http url not in LLM_MCP_HTTP_ALLOWLIST: {url}")
    import httpx

    payload = {"jsonrpc": "2.0", "id": 2, "method": method}
    if params is not None:
        payload["params"] = params
    with httpx.Client(timeout=30.0) as client:
        response = client.post(url, json=payload)
        response.raise_for_status()
        body = response.json()
    if not isinstance(body, dict):
        raise RuntimeError("invalid mcp http response")
    return body


def _call_mcp_method(
    server: LlmMcpServerConfig,
    *,
    method: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    transport = (server.transport or "stdio").strip().lower()
    if transport in ("http", "sse"):
        response = _call_mcp_http(server, method=method, params=params)
        error = response.get("error")
        if isinstance(error, dict):
            raise RuntimeError(str(error.get("message") or "mcp call failed"))
        return response.get("result") if isinstance(response.get("result"), dict) else {}
    proc = _spawn_stdio_server(server)
    try:
        _initialize_server(proc)
        response = _call_jsonrpc(proc, req_id=2, method=method, params=params)
    finally:
        proc.terminate()
    if "error" in response:
        error = response["error"]
        if isinstance(error, dict):
            raise RuntimeError(str(error.get("message") or "mcp call failed"))
        raise RuntimeError(str(error))
    result = response.get("result")
    return result if isinstance(result, dict) else {}


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
    for server in get_llm_config().mcp_servers:
        try:
            tools = list_mcp_tools(server)
        except Exception:
            continue
        for tool_row in tools:
            name = _tool_name(server.id, tool_row)
            if name in _MCP_TOOL_NAMES:
                continue
            register_tool(build_mcp_tool_spec(server, tool_row))
            _MCP_TOOL_NAMES.add(name)
            count += 1
    return count
