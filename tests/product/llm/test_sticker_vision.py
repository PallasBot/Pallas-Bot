import pytest

from pallas.product.llm.config import LlmConfig
from pallas.product.llm.sticker_vision import build_sticker_vision_stats, parse_sticker_vision_choice


def test_parse_sticker_vision_choice_accepts_json_index() -> None:
    assert parse_sticker_vision_choice('{"index":2}', candidate_count=4) == 1


def test_parse_sticker_vision_choice_rejects_out_of_range_or_explanation() -> None:
    assert parse_sticker_vision_choice('{"index":5}', candidate_count=4) is None
    assert parse_sticker_vision_choice('{"index":true}', candidate_count=4) is None
    assert parse_sticker_vision_choice("我选第 2 张", candidate_count=4) is None


def test_sticker_vision_default_timeout_is_fifteen_seconds() -> None:
    assert LlmConfig().llm_sticker_vision_timeout_sec == 15.0


def test_build_sticker_vision_stats_exposes_result_delivery_and_recent_error() -> None:
    stats = build_sticker_vision_stats(
        [
            {
                "job_id": "job-ok",
                "created_at": 100.0,
                "payload": {
                    "vision_observation": {
                        "state": "selected",
                        "candidate_count": 4,
                        "provider": "yunwu",
                        "model": "gemini-2.5-flash-image",
                        "duration_ms": 840,
                    },
                    "delivery": {"state": "sent"},
                },
            },
            {
                "job_id": "job-fail",
                "created_at": 200.0,
                "payload": {
                    "vision_observation": {
                        "state": "failed",
                        "candidate_count": 3,
                        "provider": "yunwu",
                        "model": "gemini-2.5-flash-image",
                        "duration_ms": 1200,
                        "error": "TimeoutError: request timed out",
                    },
                    "delivery": {"state": "pending"},
                },
            },
        ],
        recent_limit=2,
    )

    assert stats["requests"] == 2
    assert stats["selected"] == 1
    assert stats["failed"] == 1
    assert stats["sent"] == 1
    assert stats["candidate_total"] == 7
    assert stats["avg_duration_ms"] == 1020
    assert stats["recent_error"] == "TimeoutError: request timed out"
    assert stats["recent"][0]["job_id"] == "job-fail"


@pytest.mark.asyncio
async def test_enqueue_sticker_vision_job_records_durable_delivery_target(monkeypatch) -> None:
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from pallas.product.llm import sticker_vision

    store = SimpleNamespace(enqueue=AsyncMock(side_effect=lambda job: job))
    monkeypatch.setattr(sticker_vision, "build_work_job_store", lambda: store)

    await sticker_vision.enqueue_sticker_vision_job(
        [("[CQ:image,file=a.jpg]", b"a")],
        user_text="笑死",
        timeout_sec=8,
        idempotency_key="sticker:test",
        bot_id=100,
        group_id=200,
        fallback_cq_code="[CQ:image,file=a.jpg]",
    )

    job = store.enqueue.await_args.args[0]
    assert job.payload["delivery"] == {
        "state": "pending",
        "bot_id": 100,
        "group_id": 200,
        "fallback_cq_code": "[CQ:image,file=a.jpg]",
    }
