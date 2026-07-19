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

from pallas.product.llm.client import delete_llm_chat_session, submit_chat_task
from pallas.product.llm.config import LlmConfig, clear_llm_config_cache
from pallas.product.llm.models import ChatSubmitRequest
from pallas.product.llm.session_store import (
    append_llm_message,
    clear_user_llm_messages,
    is_llm_session_store_available,
)

INTEGRATION_BOT_ID = 10001
INTEGRATION_GROUP_ID = 20002
INTEGRATION_USER_ID = 30003

MEMORY_TEST_TEXTS = (
    "记住：我叫小明。",
    "我刚才说我叫什么？只回答名字。",
)


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
        self.wfile.write(json.dumps({"message": "ok"}).encode())


def start_callback_server(host: str, port: int) -> tuple[HTTPServer, int]:
    for attempt in range(20):
        candidate = port + attempt
        try:
            server = HTTPServer((host, candidate), CallbackHandler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            return server, candidate
        except OSError as exc:
            if exc.errno != 98:
                raise
    raise OSError(f"无法在 {host}:{port} 起 {20} 个连续端口上启动 callback 服务")


def session_mode_label() -> str:
    return "pg" if is_llm_session_store_available() else "redis"


async def persist_round_messages(
    *,
    group_id: int,
    user_text: str,
    assistant_text: str,
) -> None:
    if not is_llm_session_store_available():
        return
    await append_llm_message(INTEGRATION_BOT_ID, group_id, INTEGRATION_USER_ID, "user", user_text)
    await append_llm_message(
        INTEGRATION_BOT_ID,
        group_id,
        INTEGRATION_USER_ID,
        "assistant",
        assistant_text,
    )


async def cleanup_session(session_id: str, group_id: int, cfg: LlmConfig) -> None:
    if is_llm_session_store_available():
        removed = await clear_user_llm_messages(INTEGRATION_BOT_ID, group_id, INTEGRATION_USER_ID)
        print(f"已清理 PG 会话记录 {removed} 条")
        return
    await delete_llm_chat_session(session_id, cfg=cfg)


async def submit_and_wait(
    *,
    cfg: LlmConfig,
    session_id: str,
    user_text: str,
    mode: str,
    timeout_sec: float,
    round_no: int,
    total_rounds: int,
) -> tuple[int, str | None]:
    request_id = str(ULID())
    print(f"[轮次 {round_no}/{total_rounds}] 提交 request_id={request_id} text={user_text[:80]!r}")

    result = await submit_chat_task(
        ChatSubmitRequest(
            request_id=request_id,
            session_id=session_id,
            user_text=user_text,
            system_prompt="你是帕拉斯，简短友好地回复。若用户要求只回答名字，只输出名字。",
            bot_id=INTEGRATION_BOT_ID,
            group_id=INTEGRATION_GROUP_ID,
            user_id=INTEGRATION_USER_ID,
            mode=mode,
            token_count=80 if mode == "drunk" else None,
        ),
        cfg=cfg,
    )
    if not result.ok:
        print(f"提交失败: status={result.status} task_id={result.task_id!r}")
        return 1, None

    print(f"      已入队 task_id={result.task_id}，等待 callback…")
    payload = CALLBACK_STATE.get(request_id, timeout_sec)
    if payload is None:
        print("超时：未收到 AI callback。请确认 LLM_CHAT_ENABLED=true 且 celery worker 在跑。")
        return 2, None

    status = payload.get("status", "")
    text = unquote_plus(payload.get("text", "") or "")
    print(f"      callback status={status}")
    if text:
        print(f"      reply: {text[:500]}")
    if status != "success" or not text.strip():
        return 3, None
    return 0, text


async def maybe_init_pg() -> None:
    import nonebot
    from nonebot.adapters.onebot.v11 import Adapter as ONEBOT_V11Adapter

    try:
        nonebot.get_driver()
    except ValueError:
        nonebot.init()
        nonebot.get_driver().register_adapter(ONEBOT_V11Adapter)
    from pallas.core.foundation.db import init_db

    await init_db()
    print(f"PostgreSQL 已初始化，会话模式={session_mode_label()}")


async def run_integration(
    *,
    ai_host: str,
    ai_port: int,
    callback_port: int,
    mode: str,
    texts: list[str],
    session_id: str,
    timeout_sec: float,
    init_db: bool,
) -> int:
    clear_llm_config_cache()
    if init_db:
        await maybe_init_pg()
    cfg = LlmConfig(
        ai_server_host=ai_host,
        ai_server_port=ai_port,
        llm_chat_enabled=True,
        use_unified_chat_api=True,
        llm_governance_enabled=False,
        chat_timeout_sec=min(120.0, max(30.0, timeout_sec)),
    )
    server, bound_port = start_callback_server("127.0.0.1", callback_port)
    group_id = INTEGRATION_GROUP_ID

    print(f"[1/2] callback 监听 127.0.0.1:{bound_port}")
    if bound_port != callback_port:
        print(
            f"      注意：{callback_port} 已被占用，已改用 {bound_port}。"
            f" 请令 AI 仓 CALLBACK_PORT={bound_port} 并重启 celery worker。"
        )
    print(f"[2/2] 会话模式={session_mode_label()} session_id={session_id} rounds={len(texts)}")

    exit_code = 0
    for index, user_text in enumerate(texts, start=1):
        code, reply = await submit_and_wait(
            cfg=cfg,
            session_id=session_id,
            user_text=user_text,
            mode=mode,
            timeout_sec=timeout_sec,
            round_no=index,
            total_rounds=len(texts),
        )
        if code != 0:
            exit_code = code
            break
        if reply:
            await persist_round_messages(group_id=group_id, user_text=user_text, assistant_text=reply)

    await cleanup_session(session_id, group_id, cfg)
    server.shutdown()

    if exit_code == 0:
        print("联调通过。")
    return exit_code


def main() -> None:
    parser = argparse.ArgumentParser(description="Bot ↔ AI 统一 Chat 联调")
    parser.add_argument("--ai-host", default="127.0.0.1")
    parser.add_argument("--ai-port", type=int, default=9199)
    parser.add_argument("--callback-port", type=int, default=7969)
    parser.add_argument("--mode", default="normal", choices=("normal", "drunk"))
    parser.add_argument("--text", nargs="+", help="用户消息，可多次指定以测多轮")
    parser.add_argument(
        "--memory-test",
        action="store_true",
        help="两轮记忆联调（PG 或 Redis 会话）",
    )
    parser.add_argument("--session-id", default="", help="固定 session_id（Redis 模式建议指定）")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument(
        "--init-db",
        action="store_true",
        help="启动前 init_db()，用于 PG 会话联调（会话模式 pg）",
    )
    args = parser.parse_args()

    if args.memory_test:
        texts = list(MEMORY_TEST_TEXTS)
    elif args.text:
        texts = list(args.text)
    else:
        texts = ["你好，一句话自我介绍"]

    session_id = args.session_id.strip() or f"integration_{int(time.time())}"

    code = asyncio.run(
        run_integration(
            ai_host=args.ai_host,
            ai_port=args.ai_port,
            callback_port=args.callback_port,
            mode=args.mode,
            texts=texts,
            session_id=session_id,
            timeout_sec=args.timeout,
            init_db=args.init_db,
        )
    )
    raise SystemExit(code)


if __name__ == "__main__":
    main()
