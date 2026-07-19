#!/usr/bin/env python3
"""批量清理 Notion 任务库中 Status=Done 的条目。

官方 Notion MCP 暂不支持 in_trash 真正删除（会静默忽略），
因此采用 notion-move-pages 将 Done 条目移出任务库（移到 workspace 私有页）。
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from typing import Any

TASK_DS = "collection://e20ff5fd-f4f3-4295-9d05-eefbe039c312"
BATCH_SIZE = 100


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


def call_mcp_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    proc = subprocess.Popen(
        ["npx", "-y", "mcp-remote@latest", "https://mcp.notion.com/mcp"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        bufsize=1,
    )
    assert proc.stdin and proc.stdout
    send(
        proc,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "notion-cleanup-done", "version": "1.0"},
            },
        },
    )
    read_json_line(proc)
    send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})
    send(
        proc,
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
    )
    while True:
        resp = read_json_line(proc)
        if resp.get("id") == 2:
            proc.terminate()
            return resp


def mcp_text(resp: dict[str, Any]) -> str:
    return resp.get("result", {}).get("content", [{}])[0].get("text", "")


def query_done_tasks() -> list[dict[str, str]]:
    resp = call_mcp_tool(
        "notion-query-data-sources",
        {
            "data": {
                "data_source_urls": [TASK_DS],
                "query": (
                    f'SELECT url, "Name" FROM "{TASK_DS}" '
                    'WHERE "Status" = ? ORDER BY "Name"'
                ),
                "params": ["Done"],
            }
        },
    )
    if resp.get("result", {}).get("isError"):
        raise RuntimeError(mcp_text(resp))
    payload = json.loads(mcp_text(resp))
    return [
        {"url": row["url"], "name": row["Name"]}
        for row in payload.get("results", [])
    ]


def page_id_from_url(url: str) -> str:
    raw = url.rstrip("/").split("/")[-1].split("?")[0].replace("-", "")
    if len(raw) != 32:
        raise ValueError(f"invalid notion url: {url}")
    return raw


def move_batch(page_ids: list[str]) -> str:
    resp = call_mcp_tool(
        "notion-move-pages",
        {
            "page_or_database_ids": page_ids,
            "new_parent": {"type": "workspace"},
        },
    )
    if resp.get("result", {}).get("isError"):
        raise RuntimeError(mcp_text(resp))
    return mcp_text(resp)


def main() -> int:
    dry_run = "--dry-run" in sys.argv
    tasks = query_done_tasks()
    print(f"found {len(tasks)} Done tasks in database")
    if dry_run:
        for task in tasks:
            print(f"- {task['name']}")
        return 0

    moved = 0
    failed: list[str] = []
    page_ids = [page_id_from_url(task["url"]) for task in tasks]

    for start in range(0, len(page_ids), BATCH_SIZE):
        batch_ids = page_ids[start : start + BATCH_SIZE]
        batch_tasks = tasks[start : start + BATCH_SIZE]
        try:
            result = move_batch(batch_ids)
            moved += len(batch_ids)
            print(f"moved batch {start // BATCH_SIZE + 1}: {len(batch_ids)} items")
            print(result)
        except Exception as exc:  # noqa: BLE001
            for task in batch_tasks:
                failed.append(f"{task['name']}: {exc}")
            print(f"batch failed: {exc}", file=sys.stderr)
        time.sleep(0.5)

    remaining = query_done_tasks()
    print(f"done: moved {moved}, failed {len(failed)}, remaining Done in DB: {len(remaining)}")
    if failed:
        for item in failed:
            print(f"  - {item}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
