#!/usr/bin/env python3
"""调用 Notion MCP 工具并打印 JSON 结果。"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
from typing import Any


def read_json_line(proc: subprocess.Popen[str]) -> dict[str, Any]:
    while True:
        line = proc.stdout.readline()
        if not line:
            raise RuntimeError("mcp-remote stdout closed")
        line = line.strip()
        if not line:
            continue
        return json.loads(line)


def send(proc: subprocess.Popen[str], msg: dict[str, Any]) -> None:
    proc.stdin.write(json.dumps(msg, ensure_ascii=False) + "\n")
    proc.stdin.flush()


def call_tool(
    proc: subprocess.Popen[str],
    req_id: int,
    name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    send(
        proc,
        {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
    )
    while True:
        resp = read_json_line(proc)
        if resp.get("id") == req_id:
            return resp


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: notion_mcp_call.py <tool> [json-args]", file=sys.stderr)
        return 2
    tool = sys.argv[1]
    arguments: dict[str, Any] = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}

    proc = subprocess.Popen(
        ["npx", "-y", "mcp-remote@latest", "https://mcp.notion.com/mcp"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    assert proc.stdin and proc.stdout

    def drain_stderr() -> None:
        assert proc.stderr
        for line in proc.stderr:
            print(line, end="", file=sys.stderr)

    threading.Thread(target=drain_stderr, daemon=True).start()

    send(
        proc,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "notion-mcp-cli", "version": "1.0"},
            },
        },
    )
    read_json_line(proc)
    send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})

    result = call_tool(proc, 2, tool, arguments)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    proc.terminate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
