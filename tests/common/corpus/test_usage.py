from __future__ import annotations

from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_fetch_corpus_community_usage_does_not_raise_unbound_local(monkeypatch):
    from pallas.product.corpus import usage as mod

    mod._usage_cache = None
    mod._usage_inflight = None
    monkeypatch.setattr(mod, "corpus_community_enrollment_valid", lambda: True)
    monkeypatch.setattr(mod, "community_configured", lambda: True)
    monkeypatch.setattr(mod, "resolved_community_token", lambda: "pc_test")
    monkeypatch.setattr(mod, "resolved_community_api_base_urls", lambda: ["https://stats.example/v1/corpus"])
    fake = {
        "read_lookups": 3,
        "read_hits": 1,
        "contribute_ok": 2,
        "updated_at": 1_700_000_100,
        "source": "community_stats",
    }
    monkeypatch.setattr(mod, "_fetch_corpus_community_usage_uncached", AsyncMock(return_value=fake))
    result = await mod.fetch_corpus_community_usage()
    assert result == fake
