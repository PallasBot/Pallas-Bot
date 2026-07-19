"""Bot ↔ AI repeater fallback / select / polish 联调：模拟接话 LLM 提交并等待 callback。"""

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

from pallas.product.llm.client import delete_llm_chat_session, submit_chat_task
from pallas.product.llm.config import LlmConfig, clear_llm_config_cache
from pallas.product.llm.models import ChatSubmitRequest
from pallas.product.llm.select import build_select_user_text, load_select_system_prompt
from pallas.product.persona.compile_persona_prompt import load_base_system_prompt


def build_polish_user_text(candidate: str, *, style_suffix: str = "") -> str:
    text = (candidate or "").strip()
    if not text:
        return ""
    suffix = (style_suffix or "").strip()
    polish_tail = "\n请按牛格轻改写以上回复，保持原意，只输出一句。"
    tail = f"{suffix}{polish_tail}" if suffix else polish_tail
    return f"【候选回复】{text}{tail}"


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
        llm_governance_enabled=False,
        chat_timeout_sec=min(120.0, max(30.0, timeout_sec)),
    )
    server, bound_port = start_callback_server("127.0.0.1", callback_port)
    request_id = str(ULID())
    session_id = f"integration_{scenario}_{int(time.time())}"

    if scenario == "fallback":
        prompt_user = user_text.strip()
        token_count = None
        system_prompt = load_base_system_prompt().strip() or "你是帕拉斯，简短友好地回复一句。"
        task = "repeater_fallback"
    elif scenario == "polish":
        prompt_user = build_polish_user_text(candidate, style_suffix="\n【群风格参考】长度适中。")
        token_count = 120
        system_prompt = load_base_system_prompt().strip() or "你是帕拉斯，简短友好地回复一句。"
        task = "repeater_polish"
    elif scenario == "select":
        pool = [item.strip() for item in (user_text.split("|") if "|" in user_text else [candidate, "啊？", "没事"]) if item.strip()]
        prompt_user = build_select_user_text(
            user_text.split("|")[0].strip() if "|" in user_text else user_text.strip(),
            pool,
            context_hints="群习惯：短句",
        )
        token_count = 48
        system_prompt = load_select_system_prompt() or "只输出候选编号或 0。"
        task = "repeater_select"
    else:
        print(f"未知 scenario: {scenario}")
        server.shutdown()
        return 1

    if not prompt_user:
        print("用户文本为空，跳过提交")
        server.shutdown()
        return 1

    print(f"[1/3] callback 监听 127.0.0.1:{bound_port}")
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
            task=task,
            token_count=token_count,
            temperature=0.28 if scenario == "select" else None,
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


async def run_scenarios(
    *,
    scenarios: tuple[str, ...],
    ai_host: str,
    ai_port: int,
    callback_port: int,
    user_text: str,
    candidate: str,
    timeout_sec: float,
) -> int:
    exit_code = 0
    for scenario in scenarios:
        code = await run_scenario(
            scenario=scenario,
            ai_host=ai_host,
            ai_port=ai_port,
            callback_port=callback_port,
            user_text=user_text,
            candidate=candidate,
            timeout_sec=timeout_sec,
        )
        if code != 0:
            return code
    return exit_code


def main() -> None:
    parser = argparse.ArgumentParser(description="Bot ↔ AI repeater fallback/select/polish 联调")
    parser.add_argument(
        "--scenario",
        default="select",
        choices=("fallback", "select", "polish", "both", "select_fallback"),
        help="fallback=语料 miss；select=情绪选句；polish=遗留润色",
    )
    parser.add_argument("--ai-host", default="127.0.0.1")
    parser.add_argument("--ai-port", type=int, default=9199)
    parser.add_argument("--callback-port", type=int, default=7969)
    parser.add_argument("--text", default="今天好烦", help="用户原句；select 可用「原句|候选1|候选2」")
    parser.add_argument("--candidate", default="摸摸", help="polish 候选 / select 默认候选之一")
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()

    scenario_map = {
        "both": ("fallback", "polish"),
        "select_fallback": ("select", "fallback"),
    }
    scenarios = scenario_map.get(args.scenario, (args.scenario,))
    exit_code = asyncio.run(
        run_scenarios(
            scenarios=scenarios,
            ai_host=args.ai_host,
            ai_port=args.ai_port,
            callback_port=args.callback_port,
            user_text=args.text,
            candidate=args.candidate,
            timeout_sec=args.timeout,
        )
    )
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
