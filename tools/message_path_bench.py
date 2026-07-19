#!/usr/bin/env python3
"""群消息路径压测：ingress_gate + 联邦 + 复读主流程（可选贴近生产）。

用法（仓库根）：
  uv run python tools/message_path_bench.py
  uv run python tools/message_path_bench.py --bots 30 --rounds 200
  uv run python tools/message_path_bench.py --realistic --bots 30 --rounds 80
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import AsyncMock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@dataclass
class BenchRow:
    name: str
    bots: int
    rounds: int
    avg_ms: float
    p95_ms: float
    ops_per_sec: float


_REALISTIC_BODIES = (
    "今天天气不错",
    "哈哈哈笑死我了",
    "牛牛在吗",
    "晚上吃什么",
    "这个问题有点难",
    "好的知道了",
    "？？？",
    "确实",
)


def resolve_bench_bot_ids(n: int) -> list[int]:
    try:
        from pallas.core.platform.multi_bot.fleet import get_fleet_bot_ids

        fleet = sorted(int(x) for x in get_fleet_bot_ids())
        if len(fleet) >= n:
            return fleet[:n]
        if fleet:
            return fleet + list(range(10_001, 10_001 + (n - len(fleet))))
    except Exception:
        pass
    return list(range(10_001, 10_001 + n))


def make_group_event(
    *,
    group_id: int,
    user_id: int,
    body: str,
    message_id: int,
    self_id: int = 111,
):
    from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message

    return GroupMessageEvent.model_construct(
        time=int(time.time()) + message_id,
        self_id=self_id,
        post_type="message",
        message_type="group",
        sub_type="normal",
        user_id=user_id,
        group_id=group_id,
        message_id=message_id,
        message=Message(body),
        raw_message=body,
    )


async def bench_ingress_fanout(
    *,
    bot_ids: list[int],
    rounds: int,
    monkeypatch,
) -> BenchRow:
    from nonebot.exception import IgnoredException

    monkeypatch.setattr("pallas.core.platform.shard.registry.config.is_sharding_active", lambda: False)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.ingress_gate_active", lambda: True)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.fleet_bot_ids_contains", lambda _uid: False)
    monkeypatch.setattr(
        "pallas.core.platform.ingress.gate.claim_federate_group_message_ingress",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        "pallas.core.platform.ingress.fanout_bypass.ingress_fanout_bypasses_claim",
        lambda _plain, **_: False,
    )

    from pallas.core.platform.ingress.gate import ingress_group_message_gate

    class Bot:
        def __init__(self, self_id: int):
            self.self_id = str(self_id)

    samples: list[float] = []
    gid, uid = 99_001, 42
    for r in range(rounds):
        event = make_group_event(group_id=gid, user_id=uid, body=f"bench-{r}", message_id=r)
        t0 = time.perf_counter()
        wins = 0
        for bid in bot_ids:
            try:
                await ingress_group_message_gate(Bot(bid), event)
                wins += 1
            except IgnoredException:
                pass
        samples.append((time.perf_counter() - t0) * 1000)
        assert wins == 1, f"round {r}: expected 1 winner got {wins}"

    return BenchRow(
        name="ingress_once_fanout",
        bots=len(bot_ids),
        rounds=rounds,
        avg_ms=statistics.mean(samples),
        p95_ms=statistics.quantiles(samples, n=20)[-1] if len(samples) > 1 else samples[0],
        ops_per_sec=(len(bot_ids) * rounds) / (sum(samples) / 1000),
    )


async def bench_unified_message_realistic(
    *,
    bot_ids: list[int],
    rounds: int,
    monkeypatch,
) -> BenchRow:
    """30 牛 ingress + 胜牛走复读：真实 scrub/语料/学习（无发消息）。"""
    from nonebot.exception import IgnoredException

    from pallas.core.foundation.config import BotConfig
    from pallas.product.message_scrub import is_message_scrub_blocked_async
    from pallas.core.platform.federate.ingress import (
        claim_federate_group_message_ingress,
        federate_ingress_cached_win,
    )
    from pallas.core.platform.multi_bot.dedup import (
        normalize_group_raw_message,
        should_skip_duplicate_group_event,
        try_claim_group_message_once,
    )
    from pallas.core.platform.ingress.gate import ingress_group_message_gate
    from packages.repeater import message_id_dict, message_id_lock
    from packages.repeater.learner import Learner
    from packages.repeater.model import Chat
    from packages.repeater.shard_opt import repeater_worker_handles_message

    monkeypatch.setattr(
        "packages.repeater.learn_queue.enqueue_repeater_learn",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr("packages.repeater.insert_image", AsyncMock(return_value=None))

    class BenchBot:
        def __init__(self, self_id: int):
            self.self_id = str(self_id)

    samples: list[float] = []
    uid = 42_001_234
    for r in range(rounds):
        body = _REALISTIC_BODIES[r % len(_REALISTIC_BODIES)]
        if r % 3 == 0:
            body = f"{body} {r}"
        gid = 99_000 + (r % 50)
        mid = 1_000_000 + r
        t0 = time.perf_counter()
        winner: int | None = None
        for bid in bot_ids:
            ev = make_group_event(
                group_id=gid,
                user_id=uid,
                body=body,
                message_id=mid,
                self_id=bid,
            )
            try:
                await ingress_group_message_gate(BenchBot(bid), ev)
                winner = bid
            except IgnoredException:
                pass
        if winner is None:
            continue

        event = make_group_event(
            group_id=gid,
            user_id=uid,
            body=body,
            message_id=mid,
            self_id=winner,
        )

        if not repeater_worker_handles_message(winner):
            samples.append((time.perf_counter() - t0) * 1000)
            continue

        async with message_id_lock:
            if gid not in message_id_dict:
                from collections import deque

                message_id_dict[gid] = deque(maxlen=100)
            if mid in message_id_dict[gid]:
                samples.append((time.perf_counter() - t0) * 1000)
                continue
            message_id_dict[gid].append(mid)

        norm_raw = normalize_group_raw_message(event.raw_message)
        plain_body = event.get_plaintext()
        if await should_skip_duplicate_group_event(gid, uid, norm_raw, event.time):
            samples.append((time.perf_counter() - t0) * 1000)
            continue

        if not federate_ingress_cached_win(event, include_message_time=True):
            if not await claim_federate_group_message_ingress(event, include_message_time=True):
                samples.append((time.perf_counter() - t0) * 1000)
                continue

        if not await try_claim_group_message_once(
            "repeater_ingress",
            gid,
            uid,
            plain_body,
            event.time,
        ):
            samples.append((time.perf_counter() - t0) * 1000)
            continue

        if await is_message_scrub_blocked_async(plain_text=plain_body, raw_message=norm_raw):
            samples.append((time.perf_counter() - t0) * 1000)
            continue

        config = BotConfig(winner, gid)
        can_reply = await config.is_cooldown("repeat")
        chat = Chat(event)
        if can_reply:
            await chat.find_reply_bundle()
        await Learner.learn(chat.chat_data, Chat._topics_lock, Chat._recent_topics)
        samples.append((time.perf_counter() - t0) * 1000)

    return BenchRow(
        name="unified_message_realistic",
        bots=len(bot_ids),
        rounds=len(samples),
        avg_ms=statistics.mean(samples) if samples else 0.0,
        p95_ms=statistics.quantiles(samples, n=20)[-1] if len(samples) > 1 else (samples[0] if samples else 0.0),
        ops_per_sec=len(samples) / (sum(samples) / 1000) if samples else 0.0,
    )


async def bench_federate_double_claim(
    *,
    rounds: int,
    monkeypatch,
) -> BenchRow:
    from pallas.core.platform.federate import ingress as fed_ingress

    fed_ingress.reset_federate_ingress_win_cache_for_tests()
    monkeypatch.setattr("pallas.core.platform.federate.ingress.federate_ingress_active", lambda: True)
    monkeypatch.setattr(
        "pallas.core.platform.federate.ingress.load_or_create_deployment_id",
        lambda: "bench-deploy",
    )
    claim = AsyncMock(return_value=True)
    monkeypatch.setattr(fed_ingress, "try_claim_cross_federate_message", claim)

    event = make_group_event(group_id=1, user_id=2, body="联邦双次", message_id=1)
    samples: list[float] = []
    for _ in range(rounds):
        fed_ingress.reset_federate_ingress_win_cache_for_tests()
        claim.reset_mock()
        t0 = time.perf_counter()
        assert await fed_ingress.claim_federate_group_message_ingress(event) is True
        assert await fed_ingress.claim_federate_group_message_ingress(event) is True
        samples.append((time.perf_counter() - t0) * 1000)
        assert claim.await_count == 1

    return BenchRow(
        name="federate_ingress_cache",
        bots=1,
        rounds=rounds,
        avg_ms=statistics.mean(samples),
        p95_ms=statistics.quantiles(samples, n=20)[-1] if len(samples) > 1 else samples[0],
        ops_per_sec=rounds / (sum(samples) / 1000),
    )


async def main_async(args: argparse.Namespace) -> int:
    from pallas.core.foundation.config.dotenv import apply_repo_settings_to_environ

    apply_repo_settings_to_environ()
    import nonebot

    try:
        nonebot.get_driver()
    except ValueError:
        nonebot.init()

    if args.realistic:
        from pallas.core.foundation.db import init_db

        await init_db()

    import pytest

    monkeypatch = pytest.MonkeyPatch()
    try:
        bot_ids = resolve_bench_bot_ids(args.bots)
        rows: list[BenchRow] = []
        if args.realistic:
            rows.append(
                await bench_unified_message_realistic(
                    bot_ids=bot_ids,
                    rounds=args.rounds,
                    monkeypatch=monkeypatch,
                )
            )
        else:
            rows.extend([
                await bench_ingress_fanout(bot_ids=bot_ids, rounds=args.rounds, monkeypatch=monkeypatch),
                await bench_federate_double_claim(rounds=min(args.rounds, 500), monkeypatch=monkeypatch),
            ])
    finally:
        monkeypatch.undo()

    out = ROOT / "data" / "bot" / "message_path_bench.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    import json

    out.write_text(
        json.dumps([r.__dict__ for r in rows], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Wrote {out}")
    for r in rows:
        print(
            f"{r.name}: bots={r.bots} rounds={r.rounds} "
            f"avg={r.avg_ms:.2f}ms p95={r.p95_ms:.2f}ms ops/s={r.ops_per_sec:.0f}"
        )
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Message path micro-benchmark")
    p.add_argument("--bots", type=int, default=30, help="模拟同群在线牛数量")
    p.add_argument("--rounds", type=int, default=100, help="模拟消息条数")
    p.add_argument(
        "--realistic",
        action="store_true",
        help="ingress+联邦+复读：真实 scrub/语料 find/学习（需本机 DB，不发消息）",
    )
    return asyncio.run(main_async(p.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
