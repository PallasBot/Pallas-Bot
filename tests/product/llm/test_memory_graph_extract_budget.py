"""记忆图谱抽取的每日预算闸与降级行为。"""

from __future__ import annotations

import pytest

from pallas.product.llm.config import LlmConfig
from pallas.product.llm.memory.graph import extract


def test_extract_cooldown_not_below_five_minutes() -> None:
    assert int(extract._EXTRACT_COOLDOWN_SEC) >= 300


def test_config_has_graph_extract_daily_budget() -> None:
    field = LlmConfig.model_fields["llm_memory_graph_extract_daily_budget"]
    assert field.default == 200


@pytest.mark.asyncio
async def test_extract_from_text_short_circuits_when_budget_exhausted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def fail_call(*_a, **_k):
        calls.append("called")
        raise AssertionError("LLM should not be called")

    monkeypatch.setattr(extract, "_graph_extract_budget_ok", lambda: False)
    monkeypatch.setattr(extract, "_call_extract_llm", fail_call)

    result = await extract.extract_from_text(bot_id=1, group_id=2, text="随便聊点")

    assert result["error"] == "daily budget exhausted"
    assert calls == []


@pytest.mark.asyncio
async def test_on_write_hook_short_circuits_when_budget_exhausted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def fail_extract(**_kwargs):
        calls.append("called")
        return {"entities_upserted": 1, "edges_upserted": 0}

    monkeypatch.setattr(extract, "_graph_extract_budget_ok", lambda: False)
    monkeypatch.setattr(extract, "extract_from_text", fail_extract)

    await extract.maybe_extract_after_episode_write(bot_id=1, group_id=2, text="今天一起喝了奶茶")

    assert calls == []


@pytest.mark.asyncio
async def test_extract_from_text_bumps_budget_after_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extract.clear_extract_state_for_tests()

    async def ok_llm(_text, **_k):
        return '{"entities": [], "edges": []}'

    async def ok_upsert_entity(**_kwargs):
        return {"entity_id": 1}

    async def ok_upsert_edge(**_kwargs):
        return {"edge_id": 1}

    monkeypatch.setattr(extract, "is_memory_graph_store_available", lambda: True)
    monkeypatch.setattr(extract, "_graph_extract_budget_ok", lambda: True)
    bumps: list[int] = []
    monkeypatch.setattr(extract, "_bump_graph_extract_budget", lambda: bumps.append(1))
    monkeypatch.setattr(extract, "_call_extract_llm", ok_llm)
    monkeypatch.setattr(extract, "upsert_entity", ok_upsert_entity)
    monkeypatch.setattr(extract, "upsert_edge", ok_upsert_edge)

    result = await extract.extract_from_text(bot_id=1, group_id=2, text="小明约大家周六打球")

    assert result["entities_upserted"] == 0
    assert result["edges_upserted"] == 0
    assert bumps == [1]
