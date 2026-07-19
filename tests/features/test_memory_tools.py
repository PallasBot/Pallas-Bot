"""memory builtin tools。"""

from __future__ import annotations

import pytest

from pallas.product.llm.tools.bootstrap import ensure_llm_tools_bootstrapped, reset_llm_tools_bootstrap_for_tests
from pallas.product.llm.tools.context import ToolInvokeContext
from pallas.product.llm.tools.memory import handle_memory_save, handle_memory_search
from pallas.product.llm.tools.registry import list_registered_tools


def test_memory_tools_registered() -> None:
    reset_llm_tools_bootstrap_for_tests()
    ensure_llm_tools_bootstrapped(force=True)
    names = {t.name for t in list_registered_tools()}
    assert "memory.search" in names
    assert "memory.save" in names


@pytest.mark.asyncio
async def test_memory_search_handler(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_hits(*_a, **_k):
        return [{"content": "周五开黑", "score": 9, "source": "teach"}]

    monkeypatch.setattr(
        "pallas.product.llm.tools.memory.is_llm_memory_store_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "pallas.product.llm.tools.memory.can_read_persistent_memory",
        lambda _cfg=None: True,
    )
    monkeypatch.setattr("pallas.product.llm.tools.memory.retrieve_memory_hits", fake_hits)
    ctx = ToolInvokeContext(bot_id=1, group_id=2, user_id=3)
    out = await handle_memory_search({"query": "开黑"}, context=ctx)
    assert out["ok"] is True
    assert out["hits"][0]["content"] == "周五开黑"


@pytest.mark.asyncio
async def test_memory_save_requires_group(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "pallas.product.llm.tools.memory.is_llm_memory_store_available",
        lambda: True,
    )
    ctx = ToolInvokeContext(bot_id=1, group_id=None, user_id=3)
    out = await handle_memory_save({"content": "本群周五开黑"}, context=ctx)
    assert out["ok"] is False
    assert out["error"] == "group_context_required"
    assert "群聊" in str(out.get("message") or "")
