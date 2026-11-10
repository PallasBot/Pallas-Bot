import asyncio
from threading import Event

import pytest
from pydantic import ValidationError

from pallas.console.webui import plugin_config_payload
from pallas.console.webui.env_sections import get_webui_env_section, list_webui_env_sections


def test_pb_core_plugin_config_payload(monkeypatch):
    monkeypatch.setenv("PALLAS_MESSAGE_SCRUB_ENABLED", "true")
    from pallas.console.webui.env_sections import clear_webui_env_sections_cache
    from pallas.product.message_scrub import reload_message_scrub_caches

    reload_message_scrub_caches()
    clear_webui_env_sections_cache()
    data = plugin_config_payload("pb_core")
    assert data["plugin"] == "pb_core"
    assert data.get("hot_reload") is True
    names = {f["name"] for f in data["fields"]}
    assert "greeting_fanout_texts" in names
    assert "matcher_dispatch_enabled" in names
    assert "chat_drop_on_overload" in names
    assert "smtp_user" in names
    assert "command_start" in names
    assert "community_enabled" in names
    assert "enabled" in names or "instance_secret" in names
    groups = data.get("field_groups") or []
    assert len(groups) >= 5
    assert any(g.get("id") == "command_start" or g.get("title") == "命令前缀" for g in groups)
    from packages.pb_core.config import field_section_id

    assert field_section_id("chat_drop_on_overload") == "ingress_dispatch"
    unroutable = {name for name in names if field_section_id(name) is None}
    assert unroutable == set()
    clear_webui_env_sections_cache()


def test_pb_core_gate_queue_warn_save_uses_real_webui_chain(tmp_path, monkeypatch):
    import json

    from pallas.console.webui.plugin_api import apply_plugin_config_patch
    from pallas.core.foundation.config import repo_settings, webui_export_toml
    from pallas.core.platform.ingress import dispatch_runtime_config, fast_path

    webui_path = tmp_path / "webui.json"
    monkeypatch.setattr(repo_settings, "repo_webui_settings_path", lambda: webui_path)
    monkeypatch.setattr(webui_export_toml, "export_webui_inspection_toml", lambda *_args: None)
    monkeypatch.delenv("PALLAS_GATE_QUEUE_WARN_MS", raising=False)
    repo_settings.clear_merged_repo_settings_cache()
    dispatch_runtime_config.clear_ingress_dispatch_runtime_config_cache()
    previous_threshold = fast_path.gate_queue_warn_ms()
    try:
        payload = apply_plugin_config_patch("pb_core", {"gate_queue_warn_ms": 1750})

        saved = json.loads(webui_path.read_text(encoding="utf-8"))
        assert saved["env"]["PALLAS_GATE_QUEUE_WARN_MS"] == "1750.0"
        assert fast_path.gate_queue_warn_ms() == 1750.0
        assert payload["plugin"] == "pb_core"
    finally:
        fast_path.set_gate_queue_warn_ms(previous_threshold)
        dispatch_runtime_config.clear_ingress_dispatch_runtime_config_cache()
        repo_settings.clear_merged_repo_settings_cache()


@pytest.mark.asyncio
async def test_webui_save_wins_against_slow_stale_gate_refresh(tmp_path, monkeypatch):
    from pallas.console.webui.plugin_api import apply_plugin_config_patch
    from pallas.core.foundation.config import repo_settings, webui_export_toml
    from pallas.core.platform.ingress import dispatch_runtime_config, fast_path

    webui_path = tmp_path / "webui.json"
    monkeypatch.setattr(repo_settings, "repo_webui_settings_path", lambda: webui_path)
    monkeypatch.setattr(webui_export_toml, "export_webui_inspection_toml", lambda *_args: None)
    monkeypatch.delenv("PALLAS_GATE_QUEUE_WARN_MS", raising=False)
    monkeypatch.setattr(fast_path, "_GATE_CONFIG_REFRESH_INTERVAL_SEC", 0.01, raising=False)
    repo_settings.clear_merged_repo_settings_cache()
    dispatch_runtime_config.clear_ingress_dispatch_runtime_config_cache()
    previous_threshold = fast_path.gate_queue_warn_ms()
    read_started = Event()
    release_first_read = Event()
    second_read_started = Event()
    release_second_read = Event()
    original_read = fast_path._read_gate_queue_warn_ms
    calls = 0

    def delayed_read() -> float:
        nonlocal calls
        calls += 1
        value = original_read()
        if calls == 1:
            read_started.set()
            assert release_first_read.wait(2)
        elif calls == 2:
            second_read_started.set()
            assert release_second_read.wait(2)
        return value

    monkeypatch.setattr(fast_path, "_read_gate_queue_warn_ms", delayed_read)
    try:
        apply_plugin_config_patch("pb_core", {"gate_queue_warn_ms": 1000})
        assert fast_path.gate_queue_warn_ms() == 1000.0
        fast_path.start_gate_queue_config_refresh_loop()
        assert await asyncio.wait_for(asyncio.to_thread(read_started.wait), timeout=1)

        apply_plugin_config_patch("pb_core", {"gate_queue_warn_ms": 1750})
        assert fast_path.gate_queue_warn_ms() == 1750.0

        release_first_read.set()
        assert await asyncio.wait_for(asyncio.to_thread(second_read_started.wait), timeout=1)
        assert fast_path.gate_queue_warn_ms() == 1750.0
    finally:
        release_first_read.set()
        release_second_read.set()
        await fast_path.stop_gate_queue_config_refresh_loop()
        fast_path.set_gate_queue_warn_ms(previous_threshold)
        dispatch_runtime_config.clear_ingress_dispatch_runtime_config_cache()
        repo_settings.clear_merged_repo_settings_cache()


def test_pb_core_gate_queue_warn_rejects_non_finite_value(tmp_path, monkeypatch):
    from pallas.console.webui.plugin_api import apply_plugin_config_patch
    from pallas.core.foundation.config import repo_settings, webui_export_toml
    from pallas.core.platform.ingress import dispatch_runtime_config

    webui_path = tmp_path / "webui.json"
    monkeypatch.setattr(repo_settings, "repo_webui_settings_path", lambda: webui_path)
    monkeypatch.setattr(webui_export_toml, "export_webui_inspection_toml", lambda *_args: None)
    monkeypatch.delenv("PALLAS_GATE_QUEUE_WARN_MS", raising=False)
    repo_settings.clear_merged_repo_settings_cache()
    dispatch_runtime_config.clear_ingress_dispatch_runtime_config_cache()
    try:
        with pytest.raises(ValidationError):
            apply_plugin_config_patch("pb_core", {"gate_queue_warn_ms": float("inf")})
        assert not webui_path.exists()
    finally:
        dispatch_runtime_config.clear_ingress_dispatch_runtime_config_cache()
        repo_settings.clear_merged_repo_settings_cache()


def test_list_webui_env_sections_excludes_pb_core_migrated():
    from pallas.console.webui.env_sections import clear_webui_env_sections_cache

    clear_webui_env_sections_cache()
    rows = list_webui_env_sections()
    assert rows == []


@pytest.mark.parametrize(
    "section_id",
    [
        "mail",
        "command_start",
        "message_scrub",
        "ingress_fanout",
        "ingress_dispatch",
        "control_plane",
        "corpus_federation",
    ],
)
def test_removed_sections_raise_on_public_get(section_id: str):
    with pytest.raises(ValueError, match="pb_core"):
        get_webui_env_section(section_id)
