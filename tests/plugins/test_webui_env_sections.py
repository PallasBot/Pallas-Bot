from pathlib import Path

import pytest

_MS_CFG = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "features"
    / "message_scrub"
    / "config.py"
)
skip_no_message_scrub = pytest.mark.skipif(not _MS_CFG.is_file(), reason="无 message_scrub 配置模块")


def test_list_webui_env_sections_contains_ingress_dispatch():
    from src.console.webui import list_webui_env_sections
    from src.console.webui.env_sections import clear_webui_env_sections_cache

    clear_webui_env_sections_cache()
    rows = list_webui_env_sections()
    assert any(r["id"] == "ingress_dispatch" for r in rows)


def test_ingress_dispatch_section_payload_has_field_groups():
    from src.console.webui import webui_env_section_payload
    from src.console.webui.env_sections import clear_webui_env_sections_cache

    clear_webui_env_sections_cache()
    data = webui_env_section_payload("ingress_dispatch")
    assert data["plugin"] == "ingress_dispatch"
    groups = data.get("field_groups") or []
    assert len(groups) >= 4
    field_names = {f["name"] for f in data["fields"]}
    assert "matcher_dispatch_enabled" in field_names
    assert "send_queue_max_depth" in field_names


@skip_no_message_scrub
def test_list_webui_env_sections_contains_control_plane():
    from src.console.webui import list_webui_env_sections

    rows = list_webui_env_sections()
    assert any(r["id"] == "control_plane" for r in rows)


def test_list_webui_env_sections_contains_message_scrub(monkeypatch: pytest.MonkeyPatch):
    from src.console.webui import list_webui_env_sections
    from src.console.webui.env_sections import clear_webui_env_sections_cache

    monkeypatch.setenv("PALLAS_MESSAGE_SCRUB_ENABLED", "true")
    clear_webui_env_sections_cache()
    rows = list_webui_env_sections()
    ids = {r["id"] for r in rows}
    assert "message_scrub" in ids
    clear_webui_env_sections_cache()


def test_list_webui_env_sections_hides_message_scrub_by_default(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    from src.console.webui import list_webui_env_sections
    from src.console.webui.env_sections import clear_webui_env_sections_cache

    for key in (
        "PALLAS_MESSAGE_SCRUB_ENABLED",
        "PALLAS_INBOUND_FILTER_SUBSTRINGS",
        "PALLAS_SCRUB_LEXICON_PATH",
    ):
        monkeypatch.delenv(key, raising=False)
    phantom = tmp_path / "missing.toml"
    monkeypatch.setattr(
        "src.foundation.config.repo_settings.repo_env_path",
        lambda: phantom,
    )
    monkeypatch.setattr(
        "src.foundation.config.repo_settings.repo_config_path",
        lambda: phantom,
    )
    monkeypatch.setattr(
        "src.foundation.config.repo_settings.repo_webui_settings_path",
        lambda: tmp_path / "missing.json",
    )
    monkeypatch.setattr(
        "src.foundation.config.dotenv.merged_repo_dotenv_upper",
        lambda: {},
    )
    monkeypatch.setattr(
        "src.foundation.config.dotenv.repo_layered_dotenv_files_exist",
        lambda: True,
    )
    from src.foundation.deploy_profile import clear_deploy_profile_cache
    from src.features.message_scrub import reload_message_scrub_caches

    clear_deploy_profile_cache()
    reload_message_scrub_caches()
    clear_webui_env_sections_cache()
    rows = list_webui_env_sections()
    ids = {r["id"] for r in rows}
    assert "message_scrub" not in ids
    clear_webui_env_sections_cache()


def test_list_webui_env_sections_contains_plugin_common_sections():
    from src.console.webui import list_webui_env_sections

    rows = list_webui_env_sections()
    ids = {r["id"] for r in rows}
    assert "pallas_webui" in ids
    assert "pallas_protocol" in ids
    assert "help" in ids
    assert "service_gateways" in ids


def test_service_gateways_payload_shape():
    from src.console.webui import webui_env_section_payload

    data = webui_env_section_payload("service_gateways")
    assert data["plugin"] == "service_gateways"
    assert data.get("gateway_editor") is True
    assert data.get("supports_connectivity_check") is True
    groups = data.get("field_groups") or []
    assert {g["id"] for g in groups} == {"draw", "maa", "sing"}
    names = {f["name"] for f in data["fields"]}
    assert "pallas_image_base_url" in names
    assert "maa_public_base_url" in names
    assert "sing_enable" in names


def test_field_to_env_uppercase_keys_matches_plugin_api():
    from src.console.webui import field_to_env_uppercase_keys
    from src.plugins.pallas_webui.config import Config

    m = field_to_env_uppercase_keys(Config)
    assert m["pallas_webui_enabled"] == "PALLAS_WEBUI_ENABLED"


def test_pallas_webui_section_payload_env_keys_uppercase():
    from src.console.webui import webui_env_section_payload

    data = webui_env_section_payload("pallas_webui")
    assert data["plugin"] == "pallas_webui"
    assert data["module"] == "src.plugins.pallas_webui"
    assert data.get("dev_mode_hot_reload") is True
    groups = {g["id"]: g for g in data.get("field_groups") or []}
    assert "security" in groups
    assert "pallas_webui_dev_mode" in groups["security"]["field_names"]
    assert groups["security"]["plugin_config_path"] == "/plugins/pallas_webui"
    for f in data["fields"]:
        assert f["env_key"] == f["name"].upper()


def test_pallas_webui_patch_writes_uppercase_env(tmp_path, monkeypatch):
    import json

    from src.foundation.config import repo_settings as rs
    from src.console.webui import apply_webui_env_section_patch

    webui_file = tmp_path / "webui.json"
    monkeypatch.setattr(rs, "repo_webui_settings_path", lambda: webui_file)
    apply_webui_env_section_patch("pallas_webui", {"pallas_webui_log_lines_max": 120})
    data = json.loads(webui_file.read_text(encoding="utf-8"))
    assert data["env"]["PALLAS_WEBUI_LOG_LINES_MAX"] == "120"


@skip_no_message_scrub
def test_message_scrub_payload_shape(monkeypatch: pytest.MonkeyPatch):
    from src.console.webui import webui_env_section_payload
    from src.console.webui.env_sections import clear_webui_env_sections_cache

    monkeypatch.setenv("PALLAS_MESSAGE_SCRUB_ENABLED", "true")
    clear_webui_env_sections_cache()
    data = webui_env_section_payload("message_scrub")
    assert data["plugin"] == "message_scrub"
    assert data["module"]
    names = {f["name"] for f in data["fields"]}
    assert "inbound_filter_substrings" in names
    assert "scrub_review_providers_key_present" not in names
    for f in data["fields"]:
        assert f["env_key"]
        assert f["kind"] in ("bool", "int", "float", "json", "string")
    clear_webui_env_sections_cache()


@skip_no_message_scrub
def test_message_scrub_patch_roundtrip(tmp_path, monkeypatch):
    import json

    from src.console.webui import apply_webui_env_section_patch
    from src.console.webui.env_sections import clear_webui_env_sections_cache
    from src.foundation.config import repo_settings as rs

    monkeypatch.setenv("PALLAS_MESSAGE_SCRUB_ENABLED", "true")
    clear_webui_env_sections_cache()
    webui_file = tmp_path / "webui.json"
    monkeypatch.setattr(rs, "repo_webui_settings_path", lambda: webui_file)
    apply_webui_env_section_patch("message_scrub", {"inbound_filter_substrings": "a,b"})
    data = json.loads(webui_file.read_text(encoding="utf-8"))
    assert data["env"]["PALLAS_INBOUND_FILTER_SUBSTRINGS"] == "a,b"
    clear_webui_env_sections_cache()
