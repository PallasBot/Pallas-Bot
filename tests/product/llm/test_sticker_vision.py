import pytest

from pallas.product.llm.sticker_vision import parse_sticker_vision_choice


def test_parse_sticker_vision_choice_accepts_json_index() -> None:
    assert parse_sticker_vision_choice('{"index":2}', candidate_count=4) == 1


def test_parse_sticker_vision_choice_rejects_out_of_range_or_explanation() -> None:
    assert parse_sticker_vision_choice('{"index":5}', candidate_count=4) is None
    assert parse_sticker_vision_choice('{"index":true}', candidate_count=4) is None
    assert parse_sticker_vision_choice("我选第 2 张", candidate_count=4) is None


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
