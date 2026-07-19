from pathlib import Path

import pytest

_MS_CFG = Path(__file__).resolve().parents[2] / "pallas" / "product" / "message_scrub" / "config.py"
skip_no_message_scrub = pytest.mark.skipif(not _MS_CFG.is_file(), reason="无 message_scrub 配置模块")

_REMOVED_COMMON_CONFIG_SECTIONS = frozenset({
    "cmd_perm",
    "command_limits",
    "pb_webui",
    "pb_protocol",
    "help",
    "community_stats",
    "repeater_learn",
    "mail",
    "message_scrub",
    "ingress_fanout",
    "ingress_dispatch",
    "control_plane",
    "corpus_federation",
})


def test_list_webui_env_sections_is_empty():
    from pallas.console.webui import list_webui_env_sections, webui_env_section_payload
    from pallas.console.webui.env_sections import clear_webui_env_sections_cache

    clear_webui_env_sections_cache()
    rows = list_webui_env_sections()
    assert rows == []
    data = webui_env_section_payload("llm")
    env_keys = {f["env_key"] for f in data["fields"]}
    assert "LLM_CHAT_ENABLED" in env_keys
    assert "LLM_REPEATER_MODE" in env_keys
    assert "LLM_REPEATER_FEEDBACK_ENABLED" in env_keys
    assert "LLM_REPEATER_BIAS_ENABLED" in env_keys
    assert "LLM_REPEATER_WRITEBACK_ENABLED" in env_keys
    assert "CONVERSATION_FEATURE_LEVEL" in env_keys
    assert "LLM_VECTOR_RETRIEVE" in env_keys
    assert "LLM_EMBEDDING_MODEL" in env_keys
    assert "LLM_OUTPUT_FILTER_ENABLED" in env_keys
    assert "LLM_OUTPUT_FILTER_CHAT_HARD_PHRASES" in env_keys


def test_ingress_dispatch_section_payload_has_field_groups():
    from pallas.console.webui import webui_env_section_payload
    from pallas.console.webui.env_sections import clear_webui_env_sections_cache

    clear_webui_env_sections_cache()
    data = webui_env_section_payload("ingress_dispatch")
    assert data["plugin"] == "ingress_dispatch"
    groups = data.get("field_groups") or []
    assert len(groups) >= 4
    field_names = {f["name"] for f in data["fields"]}
    assert "matcher_dispatch_enabled" in field_names
    assert "send_queue_enabled" in field_names
    assert "send_queue_max_depth" not in field_names


@skip_no_message_scrub
def test_message_scrub_not_in_common_config_list(monkeypatch: pytest.MonkeyPatch):
    from pallas.console.webui import list_webui_env_sections
    from pallas.console.webui.env_sections import clear_webui_env_sections_cache

    monkeypatch.setenv("PALLAS_MESSAGE_SCRUB_ENABLED", "true")
    clear_webui_env_sections_cache()
    rows = list_webui_env_sections()
    ids = {r["id"] for r in rows}
    assert "message_scrub" not in ids
    clear_webui_env_sections_cache()


def test_list_webui_env_sections_excludes_plugin_migrated_sections():
    from pallas.console.webui import list_webui_env_sections
    from pallas.console.webui.env_sections import clear_webui_env_sections_cache

    clear_webui_env_sections_cache()
    rows = list_webui_env_sections()
    assert rows == []
    ids = {r["id"] for r in rows}
    assert _REMOVED_COMMON_CONFIG_SECTIONS.isdisjoint(ids)


def test_removed_common_config_sections_are_unknown():
    from pallas.console.webui.env_sections import get_webui_env_section

    for section_id in _REMOVED_COMMON_CONFIG_SECTIONS:
        with pytest.raises(ValueError, match="pb_core|未知 common-config"):
            get_webui_env_section(section_id)


def test_service_gateways_payload_shape():
    from pallas.console.webui import webui_env_section_payload

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


def test_arknights_kb_payload_does_not_import_unrelated_special_sections(
    monkeypatch: pytest.MonkeyPatch,
):
    import builtins

    from pallas.console.webui import webui_env_section_payload

    real_import = builtins.__import__

    def guarded_import(name, globals_=None, locals_=None, fromlist=(), level=0):
        if name == "pallas.console.webui.community_stats_section":
            raise AssertionError("arknights_kb payload should not import community_stats_section")
        return real_import(name, globals_, locals_, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    data = webui_env_section_payload("arknights_kb")
    assert data["plugin"] == "arknights_kb"
    env_keys = {f["env_key"] for f in data["fields"]}
    assert "ARKNIGHTS_KB_ENABLED" in env_keys
    assert "ARKNIGHTS_KB_AUTO_SYNC" in env_keys


def test_field_to_env_uppercase_keys_matches_plugin_api():
    from packages.pb_webui.config import Config
    from pallas.console.webui import field_to_env_uppercase_keys

    m = field_to_env_uppercase_keys(Config)
    assert m["pallas_webui_enabled"] == "PALLAS_WEBUI_ENABLED"


def test_mail_patch_roundtrip_via_internal_section(tmp_path, monkeypatch):
    import json

    from pallas.console.webui import apply_webui_env_section_patch
    from pallas.core.foundation.config import repo_settings as rs

    webui_file = tmp_path / "webui.json"
    monkeypatch.setattr(rs, "repo_webui_settings_path", lambda: webui_file)
    apply_webui_env_section_patch("mail", {"smtp_server": "smtp.example.com"})
    data = json.loads(webui_file.read_text(encoding="utf-8"))
    assert data["env"]["PALLAS_SMTP_SERVER"] == "smtp.example.com"


def test_common_config_raw_unsupported_section():
    import pytest

    from pallas.console.webui.env_sections import webui_env_section_raw_toml

    with pytest.raises(ValueError, match="不支持"):
        webui_env_section_raw_toml("service_gateways")


@skip_no_message_scrub
def test_message_scrub_payload_shape(monkeypatch: pytest.MonkeyPatch):
    from pallas.console.webui import webui_env_section_payload
    from pallas.console.webui.env_sections import clear_webui_env_sections_cache

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

    from pallas.console.webui import apply_webui_env_section_patch
    from pallas.console.webui.env_sections import clear_webui_env_sections_cache
    from pallas.core.foundation.config import repo_settings as rs

    monkeypatch.setenv("PALLAS_MESSAGE_SCRUB_ENABLED", "true")
    clear_webui_env_sections_cache()
    webui_file = tmp_path / "webui.json"
    monkeypatch.setattr(rs, "repo_webui_settings_path", lambda: webui_file)
    apply_webui_env_section_patch("message_scrub", {"inbound_filter_substrings": "a,b"})
    data = json.loads(webui_file.read_text(encoding="utf-8"))
    assert data["env"]["PALLAS_INBOUND_FILTER_SUBSTRINGS"] == "a,b"
    clear_webui_env_sections_cache()
