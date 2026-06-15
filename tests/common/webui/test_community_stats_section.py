from src.console.webui.community_stats_section import (
    COMMUNITY_STATS_SECTION_ID,
    apply_community_stats_patch,
    community_stats_payload,
)


def test_community_stats_payload(monkeypatch):
    monkeypatch.setattr("src.features.community_stats.config.repo_env_raw_value", lambda _key: None)
    data = community_stats_payload()
    assert data["plugin"] == COMMUNITY_STATS_SECTION_ID
    assert data.get("hot_reload") is True
    names = {f["name"] for f in data["fields"]}
    assert names == {
        "community_stats_enabled",
        "community_stats_endpoint",
        "community_stats_token",
        "community_stats_interval_sec",
        "community_stats_roster_public_qq",
        "community_stats_roster_public_profile",
    }
    assert len(data["field_groups"]) == 2
    roster_group = next(g for g in data["field_groups"] if g["id"] == "roster")
    assert roster_group["title"] == "社区主站展示"
    roster_qq = next(f for f in data["fields"] if f["name"] == "community_stats_roster_public_qq")
    roster_profile = next(f for f in data["fields"] if f["name"] == "community_stats_roster_public_profile")
    assert roster_qq["kind"] == "bool"
    assert roster_qq["current"] is False
    assert roster_qq["label"] == "公开牛牛 QQ"
    assert roster_profile["current"] is True
    assert roster_profile["label"] == "公开牛牛头像昵称"
    assert "社区主站展示" in roster_profile["description"]
    assert "自愿" not in roster_qq["description"]


def test_apply_community_stats_patch_roster_flags(monkeypatch, tmp_path):
    from src.foundation.config import repo_settings as rs

    webui = tmp_path / "data" / "pallas_config" / "webui.json"
    webui.parent.mkdir(parents=True, exist_ok=True)
    webui.write_text('{"env": {}}', encoding="utf-8")
    monkeypatch.setattr(rs, "repo_webui_settings_path", lambda: webui)
    monkeypatch.setattr(rs, "_REPO_ROOT", tmp_path)
    monkeypatch.setattr("src.features.community_stats.config.repo_env_raw_value", lambda _key: None)

    out = apply_community_stats_patch({
        "community_stats_roster_public_qq": True,
        "community_stats_roster_public_profile": False,
    })
    roster_qq = next(f for f in out["fields"] if f["name"] == "community_stats_roster_public_qq")
    roster_profile = next(f for f in out["fields"] if f["name"] == "community_stats_roster_public_profile")
    assert roster_qq["current"] is True
    assert roster_profile["current"] is False
    raw = webui.read_text(encoding="utf-8")
    assert '"PALLAS_COMMUNITY_STATS_ROSTER_PUBLIC_QQ": "true"' in raw
    assert '"PALLAS_COMMUNITY_STATS_ROSTER_PUBLIC_PROFILE": "false"' in raw

    out2 = apply_community_stats_patch({"community_stats_roster_public_qq": "false"})
    roster_qq2 = next(f for f in out2["fields"] if f["name"] == "community_stats_roster_public_qq")
    assert roster_qq2["current"] is False
