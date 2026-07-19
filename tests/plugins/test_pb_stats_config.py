from packages.pb_stats.config import Config
from pallas.console.webui import apply_plugin_config_patch, plugin_config_payload
from pallas.product.community_stats.config import read_roster_public_flags


def test_pb_stats_plugin_config_payload(monkeypatch):
    monkeypatch.setattr("pallas.product.community_stats.config.repo_env_raw_value", lambda _key: None)
    from pallas.product.community_stats.config import clear_community_stats_config_cache

    clear_community_stats_config_cache()
    data = plugin_config_payload("pb_stats")
    assert data["plugin"] == "pb_stats"
    assert data.get("hot_reload") is True
    names = {f["name"] for f in data["fields"]}
    assert "enabled" in names
    assert "interval_sec" in names
    assert "roster_public_qq" in names
    groups = data.get("field_groups") or []
    assert len(groups) == 3
    reporting_group = next(g for g in groups if g["id"] == "reporting")
    assert "enabled" in reporting_group["field_names"]
    roster_group = next(g for g in groups if g["id"] == "roster")
    assert roster_group["title"] == "社区主站展示"
    roster_qq = next(f for f in data["fields"] if f["name"] == "roster_public_qq")
    roster_profile = next(f for f in data["fields"] if f["name"] == "roster_public_profile")
    assert roster_qq["kind"] == "bool"
    assert roster_qq["current"] is False
    assert roster_qq["label"] == "公开牛牛 QQ"
    assert roster_profile["current"] is True
    assert roster_profile["label"] == "公开牛牛头像昵称"
    clear_community_stats_config_cache()


def test_read_roster_public_flags_legacy(monkeypatch):
    monkeypatch.setattr(
        "pallas.product.community_stats.config.repo_env_raw_value",
        lambda key: "true" if key == "PALLAS_COMMUNITY_STATS_ROSTER_PUBLIC" else None,
    )
    qq, profile = read_roster_public_flags()
    assert qq is True
    assert profile is True


def test_apply_pb_stats_plugin_config_patch(monkeypatch, tmp_path):
    from pallas.core.foundation.config import repo_settings as rs

    webui = tmp_path / "data" / "pallas_config" / "webui.json"
    webui.parent.mkdir(parents=True, exist_ok=True)
    webui.write_text('{"env": {}}', encoding="utf-8")
    monkeypatch.setattr(rs, "repo_webui_settings_path", lambda: webui)
    monkeypatch.setattr(rs, "_REPO_ROOT", tmp_path)
    monkeypatch.setattr("pallas.product.community_stats.config.repo_env_raw_value", lambda _key: None)

    out = apply_plugin_config_patch(
        "pb_stats",
        {
            "roster_public_qq": True,
            "roster_public_profile": False,
        },
    )
    roster_qq = next(f for f in out["fields"] if f["name"] == "roster_public_qq")
    roster_profile = next(f for f in out["fields"] if f["name"] == "roster_public_profile")
    assert roster_qq["current"] is True
    assert roster_profile["current"] is False
    raw = webui.read_text(encoding="utf-8")
    assert '"PALLAS_COMMUNITY_STATS_ROSTER_PUBLIC_QQ": "true"' in raw
    assert '"PALLAS_COMMUNITY_STATS_ROSTER_PUBLIC_PROFILE": "false"' in raw


def test_community_stats_config_delegates_to_pb_stats(monkeypatch):
    from pallas.product.community_stats import config as cfg_mod

    monkeypatch.setattr("pallas.product.community_stats.config.repo_env_raw_value", lambda _key: None)
    cfg_mod.clear_community_stats_config_cache()
    from packages.pb_stats.config import get_pb_stats_config

    cfg = get_pb_stats_config()
    assert isinstance(cfg, Config)
    assert cfg.enabled is True
