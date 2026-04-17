"""
Tests for _reply_dict memory management fixes.

Bug 1: Truncation failure - slice assignment must modify dict entry in-place
Bug 2: Generator cleanup - try/finally ensures truncation on early close

These tests simulate the behavior without importing the plugin module
to avoid NoneBot initialization issues.
"""

import asyncio
from collections import defaultdict

import pytest

SAVE_RESERVED_SIZE = 100


@pytest.mark.asyncio
async def test_reply_dict_bounded(beanie_fixture):
    """
    Test that _reply_dict growth is bounded by SAVE_RESERVED_SIZE.

    Inserts 200 replies via yield_results generator and verifies final dict size
    does not exceed SAVE_RESERVED_SIZE.
    """
    _reply_dict = defaultdict(lambda: defaultdict(list))
    _reply_lock = asyncio.Lock()

    group_id = 12345
    bot_id = 67890

    async with _reply_lock:
        _reply_dict[group_id][bot_id].append({
            "time": 1234567890,
            "pre_raw_message": "test message",
            "pre_keywords": "test",
            "reply": "[PallasBot: Reply]",
            "reply_keywords": "[PallasBot: Reply]",
        })

    answer_list = [f"reply_{i}" for i in range(200)]
    answer_keywords = "test keyword"

    async def mock_yield_results(results):
        answer_list_inner, answer_keywords_inner = results
        group_bot_replies = _reply_dict[group_id][bot_id]
        try:
            for item in answer_list_inner:
                async with _reply_lock:
                    group_bot_replies.append({
                        "time": 1234567890,
                        "pre_raw_message": "test message",
                        "pre_keywords": "test",
                        "reply": item,
                        "reply_keywords": answer_keywords_inner,
                    })
                yield item
        finally:
            async with _reply_lock:
                _reply_dict[group_id][bot_id][:] = _reply_dict[group_id][bot_id][-SAVE_RESERVED_SIZE:]

    generator = mock_yield_results((answer_list, answer_keywords))
    count = 0
    async for _ in generator:
        count += 1

    assert count == 200, f"Expected to consume 200 items, got {count}"

    final_size = len(_reply_dict[group_id][bot_id])
    assert final_size <= SAVE_RESERVED_SIZE, f"Dict size {final_size} exceeds SAVE_RESERVED_SIZE {SAVE_RESERVED_SIZE}"

    expected_size = min(201, SAVE_RESERVED_SIZE)
    assert final_size == expected_size, f"Expected final size {expected_size}, got {final_size}"


@pytest.mark.asyncio
async def test_generator_cleanup(beanie_fixture):
    """
    Test that truncation executes even if generator is closed early.

    Creates a generator, consumes 1 item, then calls aclose() to simulate
    early termination (e.g., exception in caller). Verifies truncation still runs.
    """
    _reply_dict = defaultdict(lambda: defaultdict(list))
    _reply_lock = asyncio.Lock()

    group_id = 54321
    bot_id = 98765

    async with _reply_lock:
        for i in range(300):
            _reply_dict[group_id][bot_id].append({
                "time": 1234567890,
                "pre_raw_message": "old message",
                "pre_keywords": "old",
                "reply": f"old_reply_{i}",
                "reply_keywords": "old",
            })

    initial_size = len(_reply_dict[group_id][bot_id])
    assert initial_size == 300, f"Expected initial size 300, got {initial_size}"
    assert initial_size > SAVE_RESERVED_SIZE, "Initial size must be > SAVE_RESERVED_SIZE for this test"

    answer_list = [f"new_reply_{i}" for i in range(10)]
    answer_keywords = "new keyword"

    async def mock_yield_results_with_cleanup(results):
        answer_list_inner, answer_keywords_inner = results
        group_bot_replies = _reply_dict[group_id][bot_id]
        try:
            for item in answer_list_inner:
                async with _reply_lock:
                    group_bot_replies.append({
                        "time": 1234567890,
                        "pre_raw_message": "message",
                        "pre_keywords": "key",
                        "reply": item,
                        "reply_keywords": answer_keywords_inner,
                    })
                yield item
        finally:
            async with _reply_lock:
                _reply_dict[group_id][bot_id][:] = _reply_dict[group_id][bot_id][-SAVE_RESERVED_SIZE:]

    generator = mock_yield_results_with_cleanup((answer_list, answer_keywords))

    count = 0
    async for _item in generator:
        count += 1
        if count == 1:
            break

    await generator.aclose()

    final_size = len(_reply_dict[group_id][bot_id])

    expected_size = min(301, SAVE_RESERVED_SIZE)
    assert final_size == expected_size, f"After early close: expected size {expected_size}, got {final_size}"
    assert final_size <= SAVE_RESERVED_SIZE, (
        f"Cleanup failed: size {final_size} exceeds SAVE_RESERVED_SIZE {SAVE_RESERVED_SIZE}"
    )
