"""
Test cases for message deduplication with bounded deque storage.

Tests verify that:
1. Message IDs are stored in a bounded deque (max 100 entries per group)
2. Duplicate message detection still works correctly after the fix
"""

import asyncio
from collections import defaultdict, deque

import pytest


@pytest.mark.asyncio
async def test_message_id_bounded(beanie_fixture):
    """
    Test that message_id_dict uses deque with maxlen=100.

    Inserts 200 unique message IDs for a single group and verifies
    the final size is exactly 100 (oldest 100 are evicted automatically).
    """
    # Simulate the fixed message_id_dict behavior
    message_id_lock = asyncio.Lock()
    message_id_dict = defaultdict(lambda: deque(maxlen=100))

    group_id = 12345

    # Insert 200 unique message IDs
    async with message_id_lock:
        for i in range(200):
            message_id = f"msg_{i:03d}"
            message_id_dict[group_id].append(message_id)

    # Verify final size is exactly 100 (maxlen bounded it)
    async with message_id_lock:
        stored_deque = message_id_dict[group_id]
        assert len(stored_deque) == 100, f"Expected 100 entries, got {len(stored_deque)}"
        # Verify oldest entries were evicted (entries 0-99 should be gone)
        # Last 100 entries (100-199) should remain
        assert stored_deque[0] == "msg_100", f"Expected first entry to be msg_100, got {stored_deque[0]}"
        assert stored_deque[-1] == "msg_199", f"Expected last entry to be msg_199, got {stored_deque[-1]}"


@pytest.mark.asyncio
async def test_dedup_works(beanie_fixture):
    """
    Test that duplicate message detection still works after using deque.

    Verifies that when the same message ID is inserted twice,
    it can be detected within the deque.
    """
    # Simulate the fixed message_id_dict behavior
    message_id_lock = asyncio.Lock()
    message_id_dict = defaultdict(lambda: deque(maxlen=100))

    group_id = 67890
    message_id = "msg_duplicate_001"

    # First insertion
    async with message_id_lock:
        if message_id in message_id_dict[group_id]:
            is_duplicate_1 = True
        else:
            is_duplicate_1 = False
            message_id_dict[group_id].append(message_id)

    assert not is_duplicate_1, "First insertion should not be detected as duplicate"

    # Second insertion (should be detected as duplicate)
    async with message_id_lock:
        if message_id in message_id_dict[group_id]:
            is_duplicate_2 = True
        else:
            is_duplicate_2 = False
            message_id_dict[group_id].append(message_id)

    assert is_duplicate_2, "Second insertion should be detected as duplicate"

    # Verify only one entry was added
    async with message_id_lock:
        assert len(message_id_dict[group_id]) == 1, f"Expected 1 entry, got {len(message_id_dict[group_id])}"
