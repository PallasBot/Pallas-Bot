import pytest

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
    assert "smtp_user" in names
    assert "community_enabled" in names
    assert "enabled" in names or "instance_secret" in names
    groups = data.get("field_groups") or []
    assert len(groups) >= 4
    clear_webui_env_sections_cache()


def test_list_webui_env_sections_excludes_pb_core_migrated():
    from pallas.console.webui.env_sections import clear_webui_env_sections_cache

    clear_webui_env_sections_cache()
    rows = list_webui_env_sections()
    assert rows == []


@pytest.mark.parametrize(
    "section_id",
    [
        "mail",
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
