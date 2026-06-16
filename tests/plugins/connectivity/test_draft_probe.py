import asyncio

import pytest

from src.plugins.connectivity.probe_collect import probe_all_connectivity_from_draft


@pytest.mark.asyncio
async def test_probe_from_empty_draft_delegates(monkeypatch) -> None:
    called = False

    async def fake_all(*, timeout_sec: float = 15.0):
        nonlocal called
        called = True
        return []

    monkeypatch.setattr(
        "src.features.service_gateways.collect.probe_all_connectivity",
        fake_all,
    )
    await probe_all_connectivity_from_draft({})
    assert called


def test_probe_from_draft_rejects_unknown_key() -> None:
    with pytest.raises(ValueError, match="未知配置项"):
        asyncio.run(probe_all_connectivity_from_draft({"not_a_field": 1}))
