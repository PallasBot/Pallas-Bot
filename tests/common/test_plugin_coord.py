from __future__ import annotations

import pytest

from pallas.core.plugin_coord import dream, duel, maa


@pytest.mark.asyncio
async def test_duel_coord_noop_without_plugin(monkeypatch) -> None:
    monkeypatch.setattr(duel, "_get_duel_pair", None)
    monkeypatch.setattr(duel, "import_symbol_any", lambda _paths, _name: None)
    assert await duel.get_duel_pair(1) is None
    assert await duel.should_skip_repeater_learn(1, 2, "hi") is False
    assert await duel.is_duel_paired_bot_traffic(1, 2, 3) is False
    assert duel.duel_qte_blocks_greeting_user(1, "9") is False
    assert duel.reload_operators_cache() is None


def test_maa_coord_stub_without_plugin(monkeypatch) -> None:
    monkeypatch.setattr(maa, "_get_maa_config", None)
    monkeypatch.setattr(maa, "_normalize_device_id", None)
    monkeypatch.setattr(maa, "_normalize_http_path", None)
    monkeypatch.setattr(maa, "import_symbol_any", lambda _paths, _name: None)
    assert maa.normalize_device_id("dev") is None
    cfg = maa.get_maa_config()
    assert cfg.maa_seen_ttl_seconds == 300
    assert maa.normalize_http_path("api/x") == "/api/x"
    text = maa.format_maa_http_setup_help()
    assert "尚未安装 MAA 扩展" in text


def test_dream_coord_roundtrip_with_plugin() -> None:
    pytest.importorskip("packages.dream.payload")
    from packages.dream.payload import DriftPayload, drift_payload_from_dict, drift_payload_to_dict

    payload = DriftPayload(nickname="博士", text="梦话", image_bytes=b"\x89PNG")
    data = drift_payload_to_dict(payload)
    restored = drift_payload_from_dict(data)
    assert restored.nickname == "博士"
    assert restored.text == "梦话"
    assert restored.image_bytes == b"\x89PNG"
    assert dream.drift_payload_to_dict(payload)["nickname"] == "博士"
    assert dream.drift_payload_from_dict(data).text == "梦话"
