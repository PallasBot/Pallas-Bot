from __future__ import annotations

import asyncio

import pytest
from fastapi import APIRouter

from packages.pb_webui import update_api


def _config() -> object:
    class Config:
        pallas_webui_dist_zip_repo = "PallasBot/Pallas-Bot-WebUI"
        pallas_webui_dist_zip_asset = "dist.zip"
        pallas_webui_dist_zip_tag = ""
        pallas_protocol_github_token = ""

    return Config()


def _register_impl(monkeypatch: pytest.MonkeyPatch, config: object):
    monkeypatch.setattr(update_api, "_STAGGER_EXTERNAL_WARM_SEC", 0.0)
    monkeypatch.setattr(update_api, "_EXTERNAL_SEM", asyncio.Semaphore(2))
    update_api.register_update_router(APIRouter(), x="/api", plugin_config=config)
    return update_api._warm_console_read_caches_fn


def test_batch_warm_keys_splits_local_and_external() -> None:
    webui_key = "update_check_webui:repo:asset::commit:False"
    bot_key = "update_check_bot:False"

    local_keys, external_keys = update_api._batch_warm_keys(webui_key, bot_key)

    assert local_keys == [
        "instances",
        "plugins",
        "message-stats:all",
        "plugin-run-stats:all:logsrc:all:tbl:0:view:full",
        "bots",
        "system",
    ]
    assert len(local_keys) == 6
    assert external_keys == [webui_key, bot_key, "community-stats"]
    assert webui_key in external_keys
    assert bot_key in external_keys
    assert "community-stats" in external_keys


@pytest.mark.asyncio
async def test_external_semaphore_limits_concurrency_to_two(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _config()
    impl = _register_impl(monkeypatch, config)
    webui_key = update_api._webui_update_cache_key(config)
    bot_key = f"update_check_bot:{bool(config.pallas_protocol_github_token)}"
    external_keys = {webui_key, bot_key, "community-stats"}

    current_external = 0
    max_external = 0
    started: list[str] = []

    async def fake_cached_read(**kwargs: object) -> dict[str, bool]:
        nonlocal current_external, max_external
        key = str(kwargs["key"])
        started.append(key)
        if key in external_keys:
            current_external += 1
            max_external = max(max_external, current_external)
        await asyncio.sleep(0.02)
        if key in external_keys:
            current_external -= 1
        return {"ok": True}

    monkeypatch.setattr(update_api, "cached_read", fake_cached_read)

    await impl()

    assert max_external <= 2
    assert max_external == 2
    assert set(started[len(update_api._LOCAL_WARM_KEYS) :]) == external_keys


@pytest.mark.asyncio
async def test_external_batch_starts_after_local_batch(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _config()
    impl = _register_impl(monkeypatch, config)
    webui_key = update_api._webui_update_cache_key(config)
    bot_key = f"update_check_bot:{bool(config.pallas_protocol_github_token)}"
    external_keys = {webui_key, bot_key, "community-stats"}
    local_keys = set(update_api._LOCAL_WARM_KEYS)

    started: list[str] = []

    async def fake_cached_read(**kwargs: object) -> dict[str, bool]:
        started.append(str(kwargs["key"]))
        return {"ok": True}

    monkeypatch.setattr(update_api, "cached_read", fake_cached_read)

    await impl()

    assert len(started) == 9
    assert set(started[: len(local_keys)]) == local_keys
    assert set(started[len(local_keys) :]) == external_keys
