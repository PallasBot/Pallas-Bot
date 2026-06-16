from src.platform.bot_runtime.plugin_matrix import (
    CORE_PLUGIN_NAMES,
    EXTRA_PLUGIN_NAMES,
    EXTRA_PLUGIN_PACKAGES,
    extra_package_for_plugin,
    is_core_plugin,
    is_extra_plugin,
    should_load_bundled_plugin,
    uv_extra_for_plugin,
)


def test_core_plugins_include_repeater_and_help():
    assert "repeater" in CORE_PLUGIN_NAMES
    assert "help" in CORE_PLUGIN_NAMES
    assert "pallas_webui" in CORE_PLUGIN_NAMES


def test_extra_plugins_include_duel_and_maa():
    assert "duel" in EXTRA_PLUGIN_NAMES
    assert "maa" in EXTRA_PLUGIN_NAMES
    assert "draw" in EXTRA_PLUGIN_NAMES
    assert "pallas_protocol" in EXTRA_PLUGIN_NAMES
    assert "relogin_bot" in EXTRA_PLUGIN_NAMES


def test_core_excludes_protocol():
    assert "pallas_protocol" not in CORE_PLUGIN_NAMES
    assert "relogin_bot" not in CORE_PLUGIN_NAMES
    assert "pallas_webui" in CORE_PLUGIN_NAMES


def test_core_and_extra_disjoint():
    assert CORE_PLUGIN_NAMES.isdisjoint(EXTRA_PLUGIN_NAMES)


def test_extra_package_mapping():
    assert extra_package_for_plugin("duel") == "pallas-plugin-duel"
    assert extra_package_for_plugin("chat") == "pallas-plugin-ai-media"
    assert uv_extra_for_plugin("duel") == "plugins-duel"


def test_should_load_bundled_plugin_slim_mode():
    assert should_load_bundled_plugin("repeater", load_bundled_extra=False) is True
    assert should_load_bundled_plugin("duel", load_bundled_extra=False) is False
    assert should_load_bundled_plugin("duel", load_bundled_extra=True) is True
    assert should_load_bundled_plugin("pallas_protocol", load_bundled_extra=False) is False


def test_protocol_extension_status_not_installed():
    from src.platform.bot_runtime.plugin_matrix import protocol_extension_status

    row = protocol_extension_status()
    assert row["package"] == "pallas-plugin-protocol"
    assert row["install_cli"] == "uv sync --extra plugins-protocol"


def test_is_core_and_extra_helpers():
    assert is_core_plugin("repeater")
    assert not is_core_plugin("duel")
    assert is_extra_plugin("draw")
    assert not is_extra_plugin("help")
