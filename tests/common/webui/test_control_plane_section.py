from __future__ import annotations

import json

from pallas.console.webui.control_plane_section import (
    CONTROL_PLANE_SECTION_ID,
    apply_control_plane_patch,
    control_plane_payload,
)


def test_control_plane_payload_exposes_low_risk_fields(monkeypatch):
    monkeypatch.setattr("pallas.product.control_plane.webui_config.repo_env_raw_value", lambda _key: None)
    monkeypatch.setattr("pallas.console.webui.control_plane_section.repo_env_raw_value", lambda _key: None)
    data = control_plane_payload()
    assert data["plugin"] == CONTROL_PLANE_SECTION_ID
    names = {f["name"] for f in data["fields"]}
    assert "claim_ttl_sec" in names
    assert "ingress_bypass_unified" in names
    claim = next(f for f in data["fields"] if f["name"] == "claim_ttl_sec")
    assert claim["kind"] == "number"
    bypass = next(f for f in data["fields"] if f["name"] == "ingress_bypass_unified")
    assert bypass["kind"] == "bool"
    pool_group = next(g for g in data["field_groups"] if g["id"] == "pool")
    redis_group = next(g for g in data["field_groups"] if g["id"] == "redis")
    assert "ingress_bypass_unified" in pool_group["field_names"]
    assert "claim_ttl_sec" in redis_group["field_names"]


def test_apply_control_plane_patch_writes_low_risk_fields(monkeypatch, tmp_path):
    from pallas.core.foundation.config import repo_settings as rs

    webui = tmp_path / "data" / "pallas_config" / "webui.json"
    webui.parent.mkdir(parents=True, exist_ok=True)
    webui.write_text(json.dumps({"env": {}}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(rs, "repo_webui_settings_path", lambda: webui)
    monkeypatch.setattr(rs, "_REPO_ROOT", tmp_path)
    monkeypatch.setattr("pallas.product.control_plane.webui_config.repo_env_raw_value", lambda _key: None)
    monkeypatch.setattr("pallas.console.webui.control_plane_section.repo_env_raw_value", lambda _key: None)

    out = apply_control_plane_patch({"claim_ttl_sec": 7200, "ingress_bypass_unified": True})
    assert out["fields"]
    raw = webui.read_text(encoding="utf-8")
    assert "PALLAS_FEDERATE_CLAIM_TTL_SEC" in raw
    assert "PALLAS_FEDERATE_INGRESS_BYPASS_UNIFIED" in raw
