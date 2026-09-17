"""共享 LLM httpx 客户端：连接池楔死后的自愈重建。"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from pallas.product.llm import shared_httpx


@pytest.fixture(autouse=True)
def _reset_shared_client(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(shared_httpx, "_client", None)
    monkeypatch.setattr(shared_httpx, "_client_loop", None)
    monkeypatch.setattr(shared_httpx, "_pool_timeout_streak", 0)


@pytest.mark.asyncio
async def test_consecutive_pool_timeouts_rebuild_shared_client() -> None:
    first = await shared_httpx.get_llm_shared_httpx_client()
    for _ in range(shared_httpx._POOL_REBUILD_STREAK):
        shared_httpx.note_llm_http_pool_timeout()

    second = await shared_httpx.get_llm_shared_httpx_client()

    assert second is not first
    assert first.is_closed
    assert not second.is_closed


@pytest.mark.asyncio
async def test_success_between_timeouts_avoids_rebuild() -> None:
    first = await shared_httpx.get_llm_shared_httpx_client()
    shared_httpx.note_llm_http_pool_timeout()
    shared_httpx.note_llm_http_pool_timeout()
    shared_httpx.note_llm_http_success()
    shared_httpx.note_llm_http_pool_timeout()

    assert await shared_httpx.get_llm_shared_httpx_client() is first


@pytest.mark.asyncio
async def test_provider_pool_timeout_feeds_rebuild_streak(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.llm import provider_client as pc

    async def fake_post(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise httpx.PoolTimeout("pool timed out")

    monkeypatch.setattr(pc, "_post_chat_completions", fake_post)
    monkeypatch.setattr(pc, "provider_daily_budget_ok", lambda _pid: True)

    with pytest.raises(httpx.PoolTimeout):
        await pc._post_provider_chat(
            [{"role": "user", "content": "hi"}],
            base_url="https://example.test/v1",
            api_key="sk-test",
            model="demo",
            options={},
            tools=None,
            timeout_sec=5.0,
            request_method="chat_completions",
            task="llm_chat",
            provider_id="demo",
        )

    assert shared_httpx._pool_timeout_streak == 1
