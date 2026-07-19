import pytest


@pytest.mark.asyncio
async def test_should_skip_duplicate_group_event_same_sig_only_once():
    import packages.repeater as repeater_pkg

    gid, uid, raw, t = 733291779, 1234567890, "[CQ:at,qq=1] 问你晚饭吃什么", 1746358610
    assert await repeater_pkg._should_skip_duplicate_group_event(gid, uid, raw, t) is False
    assert await repeater_pkg._should_skip_duplicate_group_event(gid, uid, raw, t) is True
    assert await repeater_pkg._should_skip_duplicate_group_event(gid, uid, raw, t) is True


@pytest.mark.asyncio
async def test_should_skip_duplicate_group_event_different_time_not_skipped():
    import packages.repeater as repeater_pkg

    gid, uid, raw = 1, 2, "你好"
    assert await repeater_pkg._should_skip_duplicate_group_event(gid, uid, raw, 100) is False
    assert await repeater_pkg._should_skip_duplicate_group_event(gid, uid, raw, 101) is False


def test_normalize_group_raw_message_matches_chatdata_pattern():
    import packages.repeater as repeater_pkg

    # 与 ChatData 一致：去掉 `.image,...]` 中的可变片段
    raw = "prefix.image,subtype=9]"
    assert repeater_pkg._normalize_group_raw_message(raw) == "prefix.image]"
