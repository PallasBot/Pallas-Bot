import asyncio

import pytest

from pallas.product.service_gateways.collect import probe_all_connectivity_from_draft
from pallas.product.service_gateways.draft import draw_draft_from_values


@pytest.mark.asyncio
async def test_probe_from_empty_draft_delegates(monkeypatch) -> None:
    called = False

    async def fake_all(*, timeout_sec: float = 15.0):
        nonlocal called
        called = True
        return []

    monkeypatch.setattr(
        "pallas.product.service_gateways.collect.probe_all_connectivity",
        fake_all,
    )
    await probe_all_connectivity_from_draft({})
    assert called


def test_probe_from_draft_rejects_unknown_key() -> None:
    with pytest.raises(ValueError, match="未知配置项"):
        asyncio.run(probe_all_connectivity_from_draft({"not_a_field": 1}))


def test_draw_draft_merges_gateway_fields() -> None:
    merged = draw_draft_from_values({
        "pallas_image_base_url": "https://example.test/v1",
        "pallas_image_api_key": "test-key",
        "pallas_image_model": "demo-model",
    })
    assert merged["pallas_image_base_url"] == "https://example.test/v1"
    assert merged["pallas_image_api_key"] == "test-key"
    assert merged["pallas_image_model"] == "demo-model"
    assert "pallas_image_runtime_mode" not in merged
