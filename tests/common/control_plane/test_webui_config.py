from __future__ import annotations

import json

from pallas.product.control_plane.webui_config import (
    get_control_plane_webui_config,
    repair_misplaced_federate_redis_env,
)


def test_coord_redis_url_does_not_fallback_to_shard_redis(monkeypatch, tmp_path):
    path = tmp_path / "webui.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"env": {"REDIS_URL": "redis://127.0.0.1:6379/0"}}, ensure_ascii=False),
        encoding="utf-8",
    )
    for mod in (
        "pallas.product.control_plane.webui_config",
        "pallas.core.foundation.config.repo_settings",
    ):
        monkeypatch.setattr(f"{mod}.repo_webui_settings_path", lambda: path)
    monkeypatch.setattr(
        "pallas.product.community_stats.store.community_stats_state_path",
        lambda: tmp_path / "community_stats.json",
    )
    get_control_plane_webui_config.cache_clear()
    cfg = get_control_plane_webui_config()
    assert cfg.coord_redis_url == ""


def test_repair_removes_duplicate_coord_key(monkeypatch, tmp_path):
    path = tmp_path / "webui.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "env": {
                    "REDIS_URL": "redis://127.0.0.1:6379/0",
                    "PALLAS_COORD_REDIS_URL": "redis://127.0.0.1:6379/0",
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    for mod in (
        "pallas.product.control_plane.webui_config",
        "pallas.core.foundation.config.repo_settings",
    ):
        monkeypatch.setattr(f"{mod}.repo_webui_settings_path", lambda: path)
    assert repair_misplaced_federate_redis_env() is True
    data = json.loads(path.read_text(encoding="utf-8"))
    assert "PALLAS_COORD_REDIS_URL" not in data["env"]
    assert data["env"]["REDIS_URL"] == "redis://127.0.0.1:6379/0"


def test_control_plane_webui_config_exposes_low_risk_federate_fields(monkeypatch):
    monkeypatch.setattr(
        "pallas.product.control_plane.webui_config.repo_env_raw_value",
        lambda key: {
            "PALLAS_FEDERATE_CLAIM_TTL_SEC": "7200",
            "PALLAS_FEDERATE_INGRESS_BYPASS_UNIFIED": "true",
        }.get(key),
    )
    monkeypatch.setattr(
        "pallas.product.community_stats.store.load_community_stats_state",
        dict,
    )
    from pallas.product.control_plane.webui_config import clear_control_plane_webui_config_cache

    clear_control_plane_webui_config_cache()
    cfg = get_control_plane_webui_config()
    assert cfg.claim_ttl_sec == 7200
    assert cfg.ingress_bypass_unified is True
