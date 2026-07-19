from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_dream_session_ingress_passes_without_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.core.platform.ingress.dream_host_gate import dream_session_ingress_passes

    monkeypatch.setattr(
        "pallas.core.platform.multi_bot.dedup.needs_group_host_bot_gate",
        lambda: True,
    )

    async def _holder(*_args, **_kwargs) -> bool:
        return True

    monkeypatch.setattr(
        "pallas.core.platform.multi_bot.dedup.is_group_owned_gate_holder",
        _holder,
    )

    assert await dream_session_ingress_passes(111, 733291779) is True


@pytest.mark.asyncio
async def test_dream_session_ingress_blocks_non_host(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.core.platform.ingress.dream_host_gate import dream_session_ingress_passes

    async def _holder(plugin: str, group_id: int, bot_id: int) -> bool:
        assert plugin == "dream"
        assert group_id == 733291779
        return bot_id == 111

    monkeypatch.setattr(
        "pallas.core.platform.multi_bot.dedup.needs_group_host_bot_gate",
        lambda: True,
    )
    monkeypatch.setattr(
        "pallas.core.platform.multi_bot.dedup.is_group_owned_gate_holder",
        _holder,
    )

    assert await dream_session_ingress_passes(111, 733291779) is True
    assert await dream_session_ingress_passes(222, 733291779) is False
