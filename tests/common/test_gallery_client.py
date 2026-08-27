from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import httpx
import pytest

from pallas.product.community_stats.gallery_client import (
    create_gallery_post,
    delete_gallery_post,
    list_gallery_posts,
)
from pallas.product.community_stats.store import (
    load_local_gallery_posts,
    reset_community_stats_state_cache_for_tests,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def community_state_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "community_stats.json"
    monkeypatch.setattr(
        "pallas.product.community_stats.store.community_stats_state_path",
        lambda: path,
    )
    reset_community_stats_state_cache_for_tests()
    return path


@pytest.fixture(autouse=True)
def clear_config_cache():
    from pallas.product.community_stats import config as cfg_mod

    cfg_mod.clear_community_stats_config_cache()
    yield
    cfg_mod.clear_community_stats_config_cache()


@pytest.mark.asyncio
async def test_list_gallery_posts_mine_falls_back_to_local(community_state_file: Path, monkeypatch):
    monkeypatch.delenv("PALLAS_COMMUNITY_STATS_ENDPOINT", raising=False)
    from pallas.product.community_stats.store import add_local_gallery_post

    add_local_gallery_post(id="local-1", text="offline post", nickname="牛牛", source="manual")

    async def fail_get(self, url, **kwargs):
        raise httpx.ConnectError("offline", request=MagicMock())

    monkeypatch.setattr("pallas.product.community_stats.config.repo_env_raw_value", lambda key: None)
    with patch.object(httpx.AsyncClient, "get", fail_get):
        data = await list_gallery_posts(mine=True)

    assert data["posts"][0]["id"] == "local-1"
    assert data["did_fail"] is True


@pytest.mark.asyncio
async def test_create_gallery_post_keeps_local_copy_on_remote_failure(
    community_state_file: Path,
    monkeypatch,
):
    monkeypatch.delenv("PALLAS_COMMUNITY_STATS_ENDPOINT", raising=False)
    monkeypatch.setattr("pallas.product.community_stats.config.repo_env_raw_value", lambda key: None)

    async def fail_post(self, url, **kwargs):
        raise httpx.ConnectError("offline", request=MagicMock())

    with patch.object(httpx.AsyncClient, "post", fail_post):
        data = await create_gallery_post(text="hello", nickname="牛牛", source="manual")

    assert data["text"] == "hello"
    posts = load_local_gallery_posts()
    assert len(posts) == 1
    assert posts[0]["text"] == "hello"


@pytest.mark.asyncio
async def test_delete_gallery_post_removes_local_even_if_remote_fails(
    community_state_file: Path,
    monkeypatch,
):
    monkeypatch.delenv("PALLAS_COMMUNITY_STATS_ENDPOINT", raising=False)
    monkeypatch.setattr("pallas.product.community_stats.config.repo_env_raw_value", lambda key: None)
    from pallas.product.community_stats.store import add_local_gallery_post

    add_local_gallery_post(id="local-1", text="x", nickname="牛牛", source="manual")

    async def fail_delete(self, url, **kwargs):
        raise httpx.ConnectError("offline", request=MagicMock())

    with patch.object(httpx.AsyncClient, "delete", fail_delete):
        data = await delete_gallery_post("local-1")

    assert data["ok"] is True
    assert load_local_gallery_posts() == []
