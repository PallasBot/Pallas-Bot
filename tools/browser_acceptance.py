#!/usr/bin/env python3
"""浏览器级 UI 验收：用 CDP 驱动 headless chromium 对页面做断言。

阶段 3「浏览器级 UI 验收」的轻量实现。不引入 playwright/selenium 依赖，
而是通过 Chrome DevTools Protocol（CDP）经 ``websockets`` 直接驱动本机
headless chromium（Google Chrome for Testing），对目标 URL 求值一组 JS
断言表达式，输出稳定 JSON 结果。

隐私约束：断言表达式与结果默认不包含消息正文/密钥；页面正文只在显式
``--dump-text`` 时输出（仅本地排障）。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import time
import urllib.request
from pathlib import Path
from typing import Any

import websockets

# 常见 headless chromium 候选路径（Playwright 缓存 + 系统安装）。
_CHROME_CANDIDATES = (
    "/root/.cache/ms-playwright/chromium-1228/chrome-linux64/chrome",
    "/root/.cache/ms-playwright/chromium_headless_shell-1228/chrome-linux64/headless_shell",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
)


def find_chrome() -> str | None:
    for candidate in _CHROME_CANDIDATES:
        if Path(candidate).is_file():
            return candidate
    return shutil.which("chromium") or shutil.which("google-chrome") or shutil.which("chrome")


def _wait_for_pages(port: int, *, timeout: float = 15.0) -> list[dict[str, Any]]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=1) as resp:
                pages = json.load(resp)
            if pages:
                return pages
        except Exception:
            pass
        time.sleep(0.2)
    raise RuntimeError(f"CDP endpoint did not expose any page target on port {port}")


async def _evaluate(ws_url: str, expression: str, *, timeout_s: float = 10.0) -> dict[str, Any]:
    async with websockets.connect(ws_url, max_size=2**24) as ws:
        await ws.send(
            json.dumps({
                "id": 1,
                "method": "Runtime.evaluate",
                "params": {"expression": expression, "returnByValue": True},
            })
        )
        while True:
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=timeout_s))
            if msg.get("id") == 1:
                return msg
            if msg.get("method") == "Runtime.exceptionThrown":
                return {"error": str(msg.get("params"))}


async def _run_assertions(
    ws_url: str,
    assertions: list[str],
    *,
    timeout_s: float = 10.0,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for index, expression in enumerate(assertions, start=1):
        response = await _evaluate(ws_url, expression, timeout_s=timeout_s)
        result: dict[str, Any] = {"index": index, "expression": expression}
        if "error" in response:
            result["status"] = "error"
            result["error"] = response["error"]
        else:
            value = (response.get("result") or {}).get("result", {}).get("value")
            result["status"] = "passed" if value else "failed"
            result["value"] = value
        results.append(result)
    return results


async def _accept(
    url: str,
    assertions: list[str],
    *,
    port: int = 9224,
    chrome: str | None = None,
    timeout_s: float = 15.0,
    dump_text: bool = False,
) -> dict[str, Any]:
    binary = chrome or find_chrome()
    if not binary:
        return {"status": "error", "error": "no chromium binary found"}
    proc = await asyncio.create_subprocess_exec(
        binary,
        "--headless=new",
        "--no-sandbox",
        "--disable-gpu",
        f"--remote-debugging-port={port}",
        url,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        pages = _wait_for_pages(port, timeout=timeout_s)
        page = next((item for item in pages if item.get("type") == "page"), pages[0])
        ws_url = page["webSocketDebuggerUrl"]
        title = await _evaluate(ws_url, "document.title", timeout_s=timeout_s)
        href = await _evaluate(ws_url, "location.href", timeout_s=timeout_s)
        assertion_results = await _run_assertions(ws_url, assertions, timeout_s=timeout_s)
        payload: dict[str, Any] = {
            "status": "passed" if all(item["status"] == "passed" for item in assertion_results) else "failed",
            "url": url,
            "title": (title.get("result") or {}).get("result", {}).get("value"),
            "href": (href.get("result") or {}).get("result", {}).get("value"),
            "assertions": assertion_results,
        }
        if dump_text:
            text = await _evaluate(ws_url, "document.body ? document.body.innerText : ''", timeout_s=timeout_s)
            payload["body_text"] = (text.get("result") or {}).get("result", {}).get("value")
        return payload
    finally:
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except TimeoutError:
            proc.kill()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="用 CDP 驱动 headless chromium 对页面做 JS 断言验收。",
    )
    parser.add_argument("url", help="要验收的页面 URL。")
    parser.add_argument(
        "--assert-expr",
        dest="assert_expr",
        action="append",
        default=[],
        help="JS 断言表达式（truthy 即通过），可重复传入。",
    )
    parser.add_argument("--port", type=int, default=9224, help="CDP 调试端口。")
    parser.add_argument("--chrome", default=None, help="显式指定 chromium 可执行文件路径。")
    parser.add_argument("--timeout", type=float, default=15.0, help="等待页面/求值超时（秒）。")
    parser.add_argument("--dump-text", action="store_true", help="输出页面正文（仅本地排障）。")
    parser.add_argument("--out", type=Path, help="可选：把结果写入 JSON 文件。")
    return parser


async def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = await _accept(
        args.url,
        args.assert_expr,
        port=args.port,
        chrome=args.chrome,
        timeout_s=args.timeout,
        dump_text=args.dump_text,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"wrote result -> {args.out}")
    return 0 if result.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
