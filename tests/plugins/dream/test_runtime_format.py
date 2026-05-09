from src.plugins.dream.echo_sample import random_echo_nickname
from src.plugins.dream.runtime import drift_at_nickname


def test_random_echo_nickname_prefixed_with_at() -> None:
    for _ in range(20):
        assert random_echo_nickname().startswith("@")


def test_drift_at_nickname_adds_at() -> None:
    assert drift_at_nickname("凯尔希") == "@凯尔希"


def test_drift_at_nickname_idempotent() -> None:
    assert drift_at_nickname("@阿米娅") == "@阿米娅"


def test_drift_at_nickname_blank_defaults() -> None:
    assert drift_at_nickname("") == "@某位博士"
    assert drift_at_nickname("   ") == "@某位博士"
