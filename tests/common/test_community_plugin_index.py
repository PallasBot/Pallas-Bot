from __future__ import annotations

import json

import pytest

from pallas.console.webui import community_plugin_index


@pytest.mark.asyncio
async def test_remote_community_index_is_cached_for_offline_fallback(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(community_plugin_index, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(community_plugin_index, "community_plugin_index_url", lambda: "https://example.test/index.json")

    async def fake_fetch(_url: str):
        return (
            "url:https://example.test/index.json",
            {"version": 2, "updated_at": "2026-08-11", "description": "test"},
            [{"plugin_id": "memes", "name": "Memes", "repository_url": "https://example.test/memes.git"}],
        )

    monkeypatch.setattr(community_plugin_index, "fetch_index_from_url", fake_fetch)

    result = await community_plugin_index.load_community_plugin_index()

    cached = json.loads((tmp_path / "data/pallas_config/community_plugin_index.json").read_text(encoding="utf-8"))
    assert result["source"] == "url:https://example.test/index.json"
    assert cached["version"] == 2
    assert cached["plugins"][0]["id"] == "memes"
