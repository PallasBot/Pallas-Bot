import asyncio
import time

import anyio

from packages.pb_webui.extended_api import (
    _matcher_elapsed_ms,
    mark_matcher_run_started,
    take_matcher_run_started,
)


class FakeMatcher:
    pass


def test_matcher_run_started_survives_anyio_task_group_child():
    """NoneBot 在 task group 子任务里跑 preprocessor，计时须挂在 matcher 实例上。"""

    async def run() -> float | None:
        matcher = FakeMatcher()

        async def child_mark() -> None:
            mark_matcher_run_started(matcher)

        async with anyio.create_task_group() as tg:
            tg.start_soon(child_mark)
        await asyncio.sleep(0.002)
        return take_matcher_run_started(matcher)

    started = asyncio.run(run())
    assert started is not None
    assert _matcher_elapsed_ms(started) >= 1.0


def test_take_matcher_run_started_clears_attr():
    matcher = FakeMatcher()
    mark_matcher_run_started(matcher)
    assert take_matcher_run_started(matcher) is not None
    assert take_matcher_run_started(matcher) is None


def test_matcher_elapsed_ms_none_is_zero():
    assert _matcher_elapsed_ms(None) == 0.0


def test_matcher_elapsed_ms_positive():
    started = time.perf_counter() - 0.01
    assert _matcher_elapsed_ms(started) >= 9.0
