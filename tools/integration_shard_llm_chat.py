"""分片 test worker LLM 联调：经 hub callback 转发，不启 mock callback。"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def bootstrap_nonebot() -> None:
    import nonebot
    from nonebot.adapters.onebot.v11 import Adapter as ONEBOT_V11Adapter

    try:
        nonebot.get_driver()
    except ValueError:
        nonebot.init()
        nonebot.get_driver().register_adapter(ONEBOT_V11Adapter)


bootstrap_nonebot()

from ulid import ULID

from pallas.product.llm.client import submit_chat_task
from pallas.product.llm.config import LlmConfig, clear_llm_config_cache
from pallas.product.llm.models import ChatSubmitRequest
from pallas.product.llm.session_store import (
    append_llm_message,
    clear_user_llm_messages,
    is_llm_session_store_available,
    list_user_llm_messages,
)
from pallas.core.foundation.config.dotenv import apply_repo_settings_to_environ
from pallas.core.platform.shard.coord.ai_task_registry import (
    ai_task_ttl_sec,
    read_ai_task_redis_sync,
    write_ai_task_redis_sync,
)

LLM_CHAT_TASK_TYPE = "llm_chat"

REGISTRY_PATH = ROOT / "data" / "pallas_shard" / "registry.json"
_default_celery = ROOT.parent / "Pallas-Bot-AI" / "logs" / "celery.log"
CELERY_LOG = Path(os.environ.get("PALLAS_AI_CELERY_LOG", str(_default_celery)))

MEMORY_TEST_TEXTS = (
    "记住：我叫小明。",
    "我刚才说我叫什么？只回答名字。",
)

INTEGRATION_GROUP_BASE = 290_000
INTEGRATION_USER_ID = 30_003


@dataclass(frozen=True)
class TestWorkerTarget:
    label: str
    shard_id: int
    worker_port: int
    bot_id: int


def ensure_dual_test_registry() -> None:
    data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    data.setdefault("test", {})
    data["test"].update({
        "enabled": True,
        "shard_id": 99,
        "port": 7978,
        "auto_assign": False,
    })
    shards: list[dict] = list(data.get("shards") or [])
    by_id = {int(row["id"]): row for row in shards if "id" in row}

    by_id[99] = {
        "id": 99,
        "port": 7978,
        "bot_ids": ["3831667476"],
        "role": "test",
    }
    by_id[98] = {
        "id": 98,
        "port": 7979,
        "bot_ids": ["1823196773"],
        "role": "test",
    }
    data["shards"] = sorted(by_id.values(), key=lambda row: int(row["id"]))
    assignments = dict(data.get("assignments") or {})
    assignments["3831667476"] = 99
    assignments["1823196773"] = 98
    data["assignments"] = assignments
    REGISTRY_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_test_workers() -> list[TestWorkerTarget]:
    data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    hub_port = int(data.get("hub_port") or 7969)
    _ = hub_port
    out: list[TestWorkerTarget] = []
    for row in data.get("shards") or []:
        if str(row.get("role") or "") != "test":
            continue
        bot_ids = [str(item).strip() for item in (row.get("bot_ids") or []) if str(item).strip()]
        if not bot_ids:
            continue
        shard_id = int(row["id"])
        out.append(
            TestWorkerTarget(
                label=f"test{shard_id}",
                shard_id=shard_id,
                worker_port=int(row["port"]),
                bot_id=int(bot_ids[0]),
            )
        )
    out.sort(key=lambda item: item.shard_id, reverse=True)
    return out


def register_shard_ai_task(
    *,
    request_id: str,
    target: TestWorkerTarget,
    group_id: int,
    user_id: int,
) -> bool:
    rec = {
        "task_id": request_id,
        "bot_id": str(target.bot_id),
        "group_id": group_id,
        "user_id": user_id,
        "shard_id": target.shard_id,
        "worker_port": target.worker_port,
        "task_type": LLM_CHAT_TASK_TYPE,
        "start_time": time.time(),
    }
    return write_ai_task_redis_sync(rec, ttl_sec=int(ai_task_ttl_sec()))


async def maybe_init_pg() -> None:
    from pallas.core.foundation.db import init_db

    await init_db()
    print(f"PostgreSQL 已初始化，会话模式={'pg' if is_llm_session_store_available() else 'redis'}")


def celery_request_done(request_id: str) -> bool:
    if not CELERY_LOG.is_file():
        return False
    try:
        text = CELERY_LOG.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return f"llm chat ok: request_id={request_id}" in text


async def wait_shard_round(
    *,
    request_id: str,
    target: TestWorkerTarget,
    bot_id: int,
    group_id: int,
    user_id: int,
    timeout_sec: float,
) -> tuple[int, str | None]:
    deadline = time.time() + timeout_sec
    before = await list_user_llm_messages(bot_id, group_id, user_id)
    before_count = len(before)

    while time.time() < deadline:
        if read_ai_task_redis_sync(request_id) is None and celery_request_done(request_id):
            messages = await list_user_llm_messages(bot_id, group_id, user_id)
            for row in reversed(messages):
                if row.role == "assistant" and len(messages) > before_count:
                    return 0, row.content.strip()
            return 3, None
        await asyncio.sleep(0.4)

    print(
        f"超时：hub→worker-test 未完成 request_id={request_id} "
        f"worker_port={target.worker_port}（请确认 Celery CALLBACK_PORT=hub 且 test worker 在跑）"
    )
    return 2, None


async def run_worker_memory_test(
    *,
    target: TestWorkerTarget,
    cfg: LlmConfig,
    timeout_sec: float,
) -> int:
    group_id = INTEGRATION_GROUP_BASE + target.shard_id
    user_id = INTEGRATION_USER_ID
    session_id = f"integration_shard_{target.shard_id}_{int(time.time())}"

    print(f"\n=== {target.label} shard={target.shard_id} bot={target.bot_id} port={target.worker_port} ===")
    for index, user_text in enumerate(MEMORY_TEST_TEXTS, start=1):
        request_id = str(ULID())
        print(f"[{target.label} 轮次 {index}/2] request_id={request_id} text={user_text[:60]!r}")

        if not register_shard_ai_task(
            request_id=request_id,
            target=target,
            group_id=group_id,
            user_id=user_id,
        ):
            print("登记 ai_task 失败：协调 Redis 不可用")
            return 4

        await append_llm_message(target.bot_id, group_id, user_id, "user", user_text)

        result = await submit_chat_task(
            ChatSubmitRequest(
                request_id=request_id,
                session_id=session_id,
                user_text=user_text,
                system_prompt="你是帕拉斯，简短友好地回复。若用户要求只回答名字，只输出名字。",
                bot_id=target.bot_id,
                group_id=group_id,
                user_id=user_id,
                mode="normal",
                task="llm_chat",
            ),
            cfg=cfg,
        )
        if not result.ok:
            print(f"提交失败: status={result.status}")
            return 1

        print(f"      已入队 task_id={result.task_id}，等待 hub→worker callback…")
        code, reply = await wait_shard_round(
            request_id=request_id,
            target=target,
            bot_id=target.bot_id,
            group_id=group_id,
            user_id=user_id,
            timeout_sec=timeout_sec,
        )
        if code != 0:
            return code
        print(f"      reply: {(reply or '')[:200]}")

    removed = await clear_user_llm_messages(target.bot_id, group_id, user_id)
    print(f"[{target.label}] 已清理 PG 会话 {removed} 条，联调通过。")
    return 0


async def run_integration(
    *,
    ai_host: str,
    ai_port: int,
    timeout_sec: float,
    init_db: bool,
    workers: list[TestWorkerTarget],
    parallel: bool,
) -> int:
    apply_repo_settings_to_environ()
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

    data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    hub_port = int(data.get("hub_port") or 7969)
    print(f"hub_port={hub_port}，Celery 须 CALLBACK_PORT={hub_port}")
    print(f"测试 worker 数={len(workers)}，并行={parallel}")

    if parallel and len(workers) > 1:
        results = await asyncio.gather(
            *[run_worker_memory_test(target=target, cfg=cfg, timeout_sec=timeout_sec) for target in workers]
        )
        return max(results)

    exit_code = 0
    for target in workers:
        code = await run_worker_memory_test(target=target, cfg=cfg, timeout_sec=timeout_sec)
        if code != 0:
            return code
    return exit_code


def main() -> None:
    parser = argparse.ArgumentParser(description="分片 test worker LLM 联调（hub callback 转发）")
    parser.add_argument("--ai-host", default="127.0.0.1")
    parser.add_argument("--ai-port", type=int, default=9099)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--init-db", action="store_true", help="启动前 init_db()（PG 会话）")
    parser.add_argument(
        "--setup-registry",
        action="store_true",
        help="写入双 test 分片注册表（99/7978、98/7979）",
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="执行分片 LLM 联调（须先 test/test2 start）",
    )
    parser.add_argument(
        "--worker",
        choices=("test", "test2", "both"),
        default="both",
        help="跑哪个测试 worker（默认 both）",
    )
    parser.add_argument(
        "--parallel",
        action="store_true",
        help="both 时并行跑两个 test worker",
    )
    args = parser.parse_args()

    if args.setup_registry:
        ensure_dual_test_registry()
        print(f"已更新 {REGISTRY_PATH}")

    if not args.run:
        if args.setup_registry:
            return
        parser.error("请指定 --run 执行联调，或 --setup-registry 仅更新注册表")

    workers = load_test_workers()
    if args.worker == "test":
        workers = [item for item in workers if item.shard_id == 99] or workers[:1]
    elif args.worker == "test2":
        workers = [item for item in workers if item.shard_id == 98]
    if not workers:
        print("未找到 role=test 的分片行，请先 --setup-registry 并启动 test worker")
        raise SystemExit(1)

    code = asyncio.run(
        run_integration(
            ai_host=args.ai_host,
            ai_port=args.ai_port,
            timeout_sec=args.timeout,
            init_db=args.init_db,
            workers=workers,
            parallel=args.parallel,
        )
    )
    if code == 0:
        print("\n分片联调全部通过。")
    raise SystemExit(code)


if __name__ == "__main__":
    main()
