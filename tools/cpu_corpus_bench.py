#!/usr/bin/env python3
"""语料 find / exists CPU 微基准（本地 mock，不访问真实 HTTP/DB）。

  uv run python tools/cpu_corpus_bench.py
"""

from __future__ import annotations

import asyncio
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pallas.product.corpus.composite_repo import CompositeContextRepository
from pallas.product.corpus.config import CorpusConfig
from pallas.product.corpus.find_cache import reset_find_cache_for_tests
from pallas.core.foundation.db.modules import Answer, Context
from tests.common.corpus.test_composite_repo import FakeContextRepo


async def bench_find(*, rounds: int) -> tuple[float, int]:
    await reset_find_cache_for_tests()
    local = FakeContextRepo(
        label="local",
        contexts={
            "kw": Context.model_construct(
                keywords="kw",
                time=1,
                trigger_count=1,
                answers=[Answer(keywords="a", group_id=1, count=1, time=1, messages=["a"])],
                ban=[],
                clear_time=0,
            )
        },
    )
    remote_calls = 0

    async def remote_find(keywords: str):
        nonlocal remote_calls
        remote_calls += 1
        return None

    remote = FakeContextRepo(label="community")
    remote.find_by_keywords = remote_find  # type: ignore[method-assign]
    cfg = CorpusConfig(merge_order=["local", "community"], merge_strategy="local_first")
    repo = CompositeContextRepository(local, community=remote, cfg=cfg)

    samples: list[float] = []
    for _ in range(rounds):
        await reset_find_cache_for_tests()
        t0 = time.perf_counter()
        await repo.find_by_keywords("kw")
        samples.append((time.perf_counter() - t0) * 1000)
    avg = statistics.mean(samples)
    return avg, remote_calls // rounds


async def main() -> None:
    rounds = 200
    avg_ms, remote_per_round = await bench_find(rounds=rounds)
    print(f"local_first find x{rounds}: avg={avg_ms:.3f}ms remote_calls_per_round={remote_per_round}")


if __name__ == "__main__":
    asyncio.run(main())
