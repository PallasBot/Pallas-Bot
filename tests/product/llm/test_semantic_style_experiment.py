from types import SimpleNamespace

import pytest

from pallas.product.llm import semantic_style_experiment as exp


@pytest.fixture(autouse=True)
def _clean_experiment_data(tmp_path, monkeypatch):
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    exp.clear_experiment_data_for_tests()
    yield
    exp.clear_experiment_data_for_tests()


def test_semantic_style_bucket_is_stable_per_group_day() -> None:
    # 2026-09-07 23:59:59 / 2026-09-08 00:00:01（北京时间）跨自然日。
    before_midnight = 1_788_710_399
    after_midnight = before_midnight + 2
    assert exp.semantic_style_day_key(before_midnight) != exp.semantic_style_day_key(after_midnight)
    assert exp.semantic_style_bucket(100, 42, now=before_midnight) == exp.semantic_style_bucket(
        100, 42, now=before_midnight
    )
    # 桶范围
    for bot in range(1, 20):
        for group in range(1, 20):
            assert 0 <= exp.semantic_style_bucket(bot, group, now=1_000_000) < 10


def test_record_exposure_and_settle(tmp_path, monkeypatch) -> None:
    exp.record_semantic_exposure(
        request_id="req-1",
        bot_id=100,
        group_id=42,
        user_id=11,
        bucket=3,
        injection_types=["behavior_pattern"],
        source_ids=["src-1"],
        delivery_source="provider",
        bot_message_id=500,
        delivered_at=1_000,
    )
    exp.mark_exposures_settled({"req-1"})
    # 已结算的不再出现在未结算列表
    assert exp._load_unsettled_exposures() == []


def test_experiment_outcome_and_circuit_trip(tmp_path, monkeypatch) -> None:
    # 未达最小样本：不熔断
    for _ in range(10):
        exp.record_experiment_outcome(
            request_id=f"warm-{_}", bucket=1, target_followup=True, negative=False
        )
    assert not exp.maybe_trip_circuit()

    # 实验 200 回合、对照 20 回合，实验负反馈率显著更高：熔断
    for _ in range(200):
        exp.record_experiment_outcome(
            request_id=f"exp-{_}", bucket=1, target_followup=False, negative=True
        )
    for _ in range(20):
        exp.record_experiment_outcome(
            request_id=f"ctl-{_}", bucket=0, target_followup=True, negative=False
        )

    assert exp.maybe_trip_circuit()
    status = exp.experiment_status()
    assert status["circuit_disabled"] is True
    assert status["circuit_reason"] == "negative_rate_delta"

    # 熔断后注入位关闭
    assert exp.semantic_style_circuit_disabled() is True

    # 人工恢复
    exp.reset_experiment_circuit()
    assert exp.semantic_style_circuit_disabled() is False
    assert exp.maybe_trip_circuit() is False


def test_circuit_not_tripped_when_rates_close(tmp_path, monkeypatch) -> None:
    for _ in range(200):
        exp.record_experiment_outcome(
            request_id=f"exp-ok-{_}", bucket=1, target_followup=True, negative=False
        )
    for _ in range(20):
        exp.record_experiment_outcome(
            request_id=f"ctl-ok-{_}", bucket=0, target_followup=True, negative=False
        )
    assert not exp.maybe_trip_circuit()


@pytest.mark.asyncio
async def test_settlement_marks_actual_rows_and_counts_each_request_once(monkeypatch) -> None:
    exp.record_semantic_exposure(
        request_id="young",
        bot_id=100,
        group_id=42,
        user_id=11,
        bucket=1,
        injection_types=[],
        source_ids=[],
        delivery_source="provider",
        bot_message_id=501,
        delivered_at=950,
    )
    exp.record_semantic_exposure(
        request_id="old",
        bot_id=100,
        group_id=42,
        user_id=11,
        bucket=1,
        injection_types=[],
        source_ids=[],
        delivery_source="provider",
        bot_message_id=502,
        delivered_at=100,
    )

    class Repo:
        async def list_group_messages_after(self, *_args, **_kwargs):
            return [
                SimpleNamespace(message_id=1, user_id=99, plain_text="想得美", raw_message=""),
                SimpleNamespace(message_id=1, user_id=99, plain_text="想得美", raw_message=""),
                SimpleNamespace(message_id=2, user_id=11, plain_text="接着聊", raw_message=""),
            ]

    monkeypatch.setattr("pallas.core.foundation.db.make_message_repository", lambda: Repo())

    assert await exp.settle_pending_semantic_exposures(now=1000) == 1
    assert [item["request_id"] for item in exp._load_unsettled_exposures()] == ["young"]
    status = exp.experiment_status()
    assert status["experiment"] == {"settled": 1, "target_followup": 1}

    exp.record_experiment_outcome(request_id="old", bucket=1, target_followup=True, negative=True)
    assert exp.experiment_status()["experiment"] == {"settled": 1, "target_followup": 1}
