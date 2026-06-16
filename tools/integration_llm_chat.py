"""Bot ↔ AI 统一 Chat 联调：提交任务并等待 callback 回执。"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import unquote_plus

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ulid import ULID

from src.features.llm.client import delete_llm_chat_session, submit_chat_task
from src.features.llm.config import LlmConfig, clear_llm_config_cache
from src.features.llm.models import ChatSubmitRequest


class CallbackState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.events: dict[str, dict] = {}

    def put(self, request_id: str, payload: dict) -> None:
        with self.lock:
            self.events[request_id] = payload

    def get(self, request_id: str, timeout_sec: float) -> dict | None:
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            with self.lock:
                if request_id in self.events:
                    return self.events.pop(request_id)
            time.sleep(0.2)
        return None


CALLBACK_STATE = CallbackState()


class CallbackHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return

    def do_POST(self) -> None:  # noqa: N802
        request_id = self.path.rstrip("/").split("/")[-1]
        length = int(self.headers.get("Content-Length", "0") or "0")
        body = self.rfile.read(length).decode("utf-8", errors="replace")
        data: dict = {}
        if body:
            for part in body.split("&"):
                if "=" in part:
                    key, value = part.split("=", 1)
                    data[key] = value
        CALLBACK_STATE.put(request_id, data)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wwrite = self.wfile.write
        self.wwrite(json.dumps({"message": "ok"}).encode())


def start_callback_server(host: str, port: int) -> HTTPServer:
    server = HTTPServer((host, port), CallbackHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


async def run_integration(
    *,
    ai_host: str,
    ai_port: int,
    callback_port: int,
    mode: str,
    user_text: str,
    timeout_sec: float,
) -> int:
    clear_llm_config_cache()
    cfg = LlmConfig(
        ai_server_host=ai_host,
        ai_server_port=ai_port,
        use_unified_chat_api=True,
        chat_timeout_sec=min(120.0, max(30.0, timeout_sec)),
    )
    server = start_callback_server("127.0.0.1", callback_port)
    request_id = str(ULID())
    session_id = f"integration_{int(time.time())}"

    print(f"[1/3] callback 监听 127.0.0.1:{callback_port}")
    print(f"[2/3] 提交 Chat mode={mode} request_id={request_id}")

    result = await submit_chat_task(
        ChatSubmitRequest(
            request_id=request_id,
            session_id=session_id,
            user_text=user_text,
            system_prompt="你是帕拉斯，简短友好地回复一句。",
            bot_id=10001,
            group_id=20002,
            user_id=30003,
            mode=mode,
            token_count=80 if mode == "drunk" else None,
        ),
        cfg=cfg,
    )
    if not result.ok:
        print(f"提交失败: status={result.status} task_id={result.task_id!r}")
        server.shutdown()
        return 1

    print(f"      已入队 task_id={result.task_id}")
    print(f"[3/3] 等待 callback（最多 {timeout_sec:.0f}s）…")

    payload = CALLBACK_STATE.get(request_id, timeout_sec)
    await delete_llm_chat_session(session_id, cfg=cfg)
    server.shutdown()

    if payload is None:
        print("超时：未收到 AI callback。请确认联调栈 LLM_CHAT_ENABLED=true 且 celery worker 在跑。")
        return 2

    status = payload.get("status", "")
    text = unquote_plus(payload.get("text", "") or "")
    print(f"callback status={status}")
    if text:
        print(f"reply: {text[:500]}")
    if status != "success" or not text.strip():
        return 3
    print("联调通过。")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Bot ↔ AI 统一 Chat 联调")
    parser.add_argument("--ai-host", default="127.0.0.1")
    parser.add_argument("--ai-port", type=int, default=9199)
    parser.add_argument("--callback-port", type=int, default=18080)
    parser.add_argument("--mode", default="normal", choices=("normal", "drunk"))
    parser.add_argument("--text", default="你好，一句话自我介绍")
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()
    code = asyncio.run(
        run_integration(
            ai_host=args.ai_host,
            ai_port=args.ai_port,
            callback_port=args.callback_port,
            mode=args.mode,
            user_text=args.text,
            timeout_sec=args.timeout,
        )
    )
    raise SystemExit(code)


if __name__ == "__main__":
    main()
