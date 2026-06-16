"""Bot ↔ AI repeater fallback / polish 联调：模拟接话 LLM 提交并等待 callback。"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.integration_llm_chat import CALLBACK_STATE, start_callback_server
from ulid import ULID

from src.features.llm.client import delete_llm_chat_session, submit_chat_task
from src.features.llm.config import LlmConfig, clear_llm_config_cache
from src.features.llm.models import ChatSubmitRequest
from src.features.llm.polish import build_polish_user_text
from src.features.persona.compile_persona_prompt import load_base_system_prompt


async def run_scenario(
    *,
    scenario: str,
    ai_host: str,
    ai_port: int,
    callback_port: int,
    user_text: str,
    candidate: str,
    timeout_sec: float,
) -> int:
    clear_llm_config_cache()
    cfg = LlmConfig(
        ai_server_host=ai_host,
        ai_server_port=ai_port,
        llm_chat_enabled=True,
        use_unified_chat_api=True,
        chat_timeout_sec=min(120.0, max(30.0, timeout_sec)),
    )
    server = start_callback_server("127.0.0.1", callback_port)
    request_id = str(ULID())
    session_id = f"integration_{scenario}_{int(time.time())}"

    if scenario == "fallback":
        prompt_user = user_text.strip()
        token_count = None
    elif scenario == "polish":
        prompt_user = build_polish_user_text(candidate, style_suffix="\n【群风格参考】长度适中。")
        token_count = 120
    else:
        print(f"未知 scenario: {scenario}")
        server.shutdown()
        return 1

    if not prompt_user:
        print("用户文本为空，跳过提交")
        server.shutdown()
        return 1

    system_prompt = load_base_system_prompt().strip() or "你是帕拉斯，简短友好地回复一句。"

    print(f"[1/3] callback 监听 127.0.0.1:{callback_port}")
    print(f"[2/3] 提交 repeater {scenario} request_id={request_id}")

    result = await submit_chat_task(
        ChatSubmitRequest(
            request_id=request_id,
            session_id=session_id,
            user_text=prompt_user,
            system_prompt=system_prompt,
            bot_id=10001,
            group_id=20002,
            user_id=30003,
            mode="normal",
            token_count=token_count,
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
        print("超时：未收到 AI callback。请确认 LLM_CHAT_ENABLED=true 且 celery worker 在跑。")
        return 2

    from urllib.parse import unquote_plus

    status = payload.get("status", "")
    text = unquote_plus(payload.get("text", "") or "")
    print(f"callback status={status}")
    if text:
        print(f"reply: {text[:500]}")
    if status != "success" or not text.strip():
        return 3
    print(f"repeater {scenario} 联调通过。")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Bot ↔ AI repeater fallback/polish 联调")
    parser.add_argument(
        "--scenario",
        default="fallback",
        choices=("fallback", "polish", "both"),
        help="fallback=语料 miss；polish=语料 hit 轻改写",
    )
    parser.add_argument("--ai-host", default="127.0.0.1")
    parser.add_argument("--ai-port", type=int, default=9199)
    parser.add_argument("--callback-port", type=int, default=18081)
    parser.add_argument("--text", default="今天天气怎么样", help="fallback 用户原句")
    parser.add_argument("--candidate", default="还行吧，挺舒服的", help="polish 候选回复")
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()

    scenarios = ("fallback", "polish") if args.scenario == "both" else (args.scenario,)
    exit_code = 0
    for index, scenario in enumerate(scenarios):
        port = args.callback_port + index
        code = asyncio.run(
            run_scenario(
                scenario=scenario,
                ai_host=args.ai_host,
                ai_port=args.ai_port,
                callback_port=port,
                user_text=args.text,
                candidate=args.candidate,
                timeout_sec=args.timeout,
            )
        )
        if code != 0:
            exit_code = code
            break
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
