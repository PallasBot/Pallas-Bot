"""dream 采集黑名单。"""

from src.plugins.dream.capture_filter import dream_capture_blocked_by_substrings


def test_dream_capture_blocked_when_plain_contains_buke() -> None:
    assert dream_capture_blocked_by_substrings("  不可以  ", "")


def test_dream_capture_blocked_when_raw_contains_buke() -> None:
    assert dream_capture_blocked_by_substrings("", "[CQ:at,qq=1] 不可以")


def test_dream_capture_not_blocked_normal() -> None:
    assert not dream_capture_blocked_by_substrings("今天天气好", "[CQ:text]")
