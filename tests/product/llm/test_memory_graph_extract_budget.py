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

    monkeypatch.setattr(extract, "_reserve_graph_extract_budget", lambda: False)
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
async def test_extract_from_text_reserves_budget_before_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def ok_llm(_text, **_k):
        return '{"entities": [], "edges": []}'

    async def ok_upsert_entity(**_kwargs):
        return {"entity_id": 1}

    async def ok_upsert_edge(**_kwargs):
        return {"edge_id": 1}

    monkeypatch.setattr(extract, "is_memory_graph_store_available", lambda: True)
    reservations: list[int] = []
    monkeypatch.setattr(extract, "_reserve_graph_extract_budget", lambda count=1: reservations.append(count) or True)
    monkeypatch.setattr(extract, "_call_extract_llm", ok_llm)
    monkeypatch.setattr(extract, "upsert_entity", ok_upsert_entity)
    monkeypatch.setattr(extract, "upsert_edge", ok_upsert_edge)

    result = await extract.extract_from_text(bot_id=1, group_id=2, text="小明约大家周六打球")

    assert result["entities_upserted"] == 0
    assert result["edges_upserted"] == 0
    assert reservations == [1]


@pytest.mark.asyncio
async def test_extract_from_text_keeps_reserved_budget_when_apply_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reservations: list[int] = []

    async def fail_apply(**_kwargs):
        raise RuntimeError("graph store failed")

    monkeypatch.setattr(extract, "is_memory_graph_store_available", lambda: True)
    monkeypatch.setattr(extract, "_reserve_graph_extract_budget", lambda count=1: reservations.append(count) or True)

    async def ok_llm(*_args, **_kwargs):
        return _ok_extract_result()

    monkeypatch.setattr(extract, "_call_extract_llm", ok_llm)
    monkeypatch.setattr(extract, "_apply_extraction_payload", fail_apply)

    with pytest.raises(RuntimeError, match="graph store failed"):
        await extract.extract_from_text(bot_id=1, group_id=2, text="小明约大家周六打球")

    assert reservations == [1]


def _ok_extract_result() -> str:
    return '{"entities": [], "edges": []}'


def test_graph_extract_budget_reserves_concurrent_slots(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    extract.clear_extract_state_for_tests()
    from pallas.product.llm import daily_budget

    monkeypatch.setattr(daily_budget, "_budget_path", lambda name: tmp_path / f"{name}_budget.json")
    monkeypatch.setattr(
        extract,
        "get_llm_config",
        lambda: type("Config", (), {"llm_memory_graph_extract_daily_budget": 1})(),
    )

    assert extract._reserve_graph_extract_budget() is True
    assert extract._reserve_graph_extract_budget() is False


def test_graph_extract_budget_reserves_a_batch_atomically(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    extract.clear_extract_state_for_tests()
    from pallas.product.llm import daily_budget

    monkeypatch.setattr(daily_budget, "_budget_path", lambda name: tmp_path / f"{name}_budget.json")
    monkeypatch.setattr(
        extract,
        "get_llm_config",
        lambda: type("Config", (), {"llm_memory_graph_extract_daily_budget": 2})(),
    )

    assert extract._reserve_graph_extract_budget(2) is True
    assert extract._reserve_graph_extract_budget() is False


def test_graph_extract_budget_persists_across_process_restart(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """预算计数落盘后，模拟进程重启（重新走 daily_budget 读文件）仍能拦住超限。"""
    extract.clear_extract_state_for_tests()
    from pallas.product.llm import daily_budget

    monkeypatch.setattr(daily_budget, "_budget_path", lambda name: tmp_path / f"{name}_budget.json")
    monkeypatch.setattr(
        extract,
        "get_llm_config",
        lambda: type("Config", (), {"llm_memory_graph_extract_daily_budget": 1})(),
    )

    assert extract._reserve_graph_extract_budget() is True
    # 模拟重启：清掉进程内状态（现在无进程内计数，直接读文件）
    extract.clear_extract_state_for_tests()
    assert extract._reserve_graph_extract_budget() is False
