from __future__ import annotations

import asyncio
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

    result = await community_plugin_index.load_community_plugin_index(force_refresh=True)

    cached = json.loads((tmp_path / "data/pallas_config/community_plugin_index.json").read_text(encoding="utf-8"))
    assert result["source"] == "url:https://example.test/index.json"
    assert cached["version"] == 2
    assert cached["plugins"][0]["id"] == "memes"


@pytest.mark.asyncio
async def test_local_community_index_returns_without_waiting_for_remote_refresh(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(community_plugin_index, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(community_plugin_index, "community_plugin_index_url", lambda: "https://example.test/index.json")
    local_index = tmp_path / "data/pallas_config/community_plugin_index.json"
    local_index.parent.mkdir(parents=True)
    local_index.write_text(
        json.dumps({
            "version": 1,
            "plugins": [
                {
                    "id": "cached",
                    "name": "Cached",
                    "repository": "https://example.test/cached.git",
                }
            ],
        }),
        encoding="utf-8",
    )

    remote_started = asyncio.Event()
    release_remote = asyncio.Event()

    async def fake_fetch(_url: str):
        remote_started.set()
        await release_remote.wait()
        return (
            "url:https://example.test/index.json",
            {"version": 2},
            [{"plugin_id": "fresh", "name": "Fresh", "repository_url": "https://example.test/fresh.git"}],
        )

    monkeypatch.setattr(community_plugin_index, "fetch_index_from_url", fake_fetch)

    result = await asyncio.wait_for(community_plugin_index.load_community_plugin_index(), timeout=0.05)

    assert result["source"] == "file:data/pallas_config/community_plugin_index.json"
    assert [plugin["plugin_id"] for plugin in result["plugins"]] == ["cached"]
    await asyncio.wait_for(remote_started.wait(), timeout=0.05)
    release_remote.set()
    await asyncio.sleep(0)
