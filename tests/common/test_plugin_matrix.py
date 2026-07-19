from pallas.core.platform.bot_runtime.plugin_matrix import (
    CORE_PLUGIN_NAMES,
    EXTRA_PACKAGE_MODULES,
    EXTRA_PLUGIN_NAMES,
    extra_package_for_plugin,
    installed_extra_plugin_modules,
    is_core_plugin,
    is_extra_plugin,
    official_extension_description,
    official_extension_display_name,
    official_extension_visuals,
    resolve_hub_bundled_module_paths,
    should_load_bundled_plugin,
    uv_extra_for_plugin,
)


def test_core_plugins_include_repeater_and_help():
    assert "pb_core" in CORE_PLUGIN_NAMES
    assert "repeater" in CORE_PLUGIN_NAMES
    assert "llm_chat" in CORE_PLUGIN_NAMES
    assert "help" in CORE_PLUGIN_NAMES
    assert "pb_webui" in CORE_PLUGIN_NAMES
    assert "pb_stats" in CORE_PLUGIN_NAMES
    assert "drink" in CORE_PLUGIN_NAMES
    assert "greeting" in CORE_PLUGIN_NAMES
    assert "roulette" in CORE_PLUGIN_NAMES
    assert "take_name" in CORE_PLUGIN_NAMES


def test_extra_plugins_include_duel_and_maa():
    assert "duel" in EXTRA_PLUGIN_NAMES
    assert "maa" in EXTRA_PLUGIN_NAMES
    assert "draw" in EXTRA_PLUGIN_NAMES
    assert "bot_status" in EXTRA_PLUGIN_NAMES
    assert "pb_protocol" in EXTRA_PLUGIN_NAMES
    assert "relogin_bot" in EXTRA_PLUGIN_NAMES


def test_core_excludes_migrated_plugins():
    assert "llm_chat" not in EXTRA_PLUGIN_NAMES
    assert "community_stats" not in CORE_PLUGIN_NAMES
    assert "community_stats" not in EXTRA_PLUGIN_NAMES
    assert "pb_protocol" not in CORE_PLUGIN_NAMES
    assert "relogin_bot" not in CORE_PLUGIN_NAMES
    assert "block" not in CORE_PLUGIN_NAMES
    assert "callback" not in CORE_PLUGIN_NAMES
    assert "ingress_gate" not in CORE_PLUGIN_NAMES
    assert "bot_status" not in CORE_PLUGIN_NAMES
    assert "duel" not in CORE_PLUGIN_NAMES
    assert "connectivity" not in CORE_PLUGIN_NAMES
    assert "pb_webui" in CORE_PLUGIN_NAMES


def test_core_and_extra_disjoint():
    assert CORE_PLUGIN_NAMES.isdisjoint(EXTRA_PLUGIN_NAMES)


def test_extra_package_mapping():
    assert extra_package_for_plugin("duel") == "pallas-plugin-duel"
    assert extra_package_for_plugin("pb_protocol") == "pallas-plugin-protocol"
    assert extra_package_for_plugin("pallas_protocol") == "pallas-plugin-protocol"
    assert extra_package_for_plugin("chat") == "pallas-plugin-ai-media"
    assert extra_package_for_plugin("bot_status") == "pallas-plugin-bot-status"
    assert uv_extra_for_plugin("duel") == "plugins-duel"
    assert uv_extra_for_plugin("bot_status") == "plugins-bot-status"


def test_should_load_bundled_plugin_slim_mode():
    assert should_load_bundled_plugin("repeater", load_bundled_extra=False) is True
    assert should_load_bundled_plugin("llm_chat", load_bundled_extra=False) is True
    assert should_load_bundled_plugin("pb_stats", load_bundled_extra=False) is True
    assert should_load_bundled_plugin("duel", load_bundled_extra=False) is False
    assert should_load_bundled_plugin("duel", load_bundled_extra=True) is True
    assert should_load_bundled_plugin("pb_protocol", load_bundled_extra=False) is False
    assert should_load_bundled_plugin("pallas_protocol", load_bundled_extra=False) is False


def test_slim_core_supports_persona_without_extras():
    """G1：无扩展包时 core 含 repeater + llm_chat，不含 duel/maa。"""
    for name in ("repeater", "llm_chat", "help", "pb_webui"):
        assert should_load_bundled_plugin(name, load_bundled_extra=False) is True
    for name in ("duel", "maa", "draw", "pb_protocol"):
        assert should_load_bundled_plugin(name, load_bundled_extra=False) is False


def test_should_load_bundled_plugin_auto_mode(monkeypatch):
    monkeypatch.setattr(
        "pallas.core.platform.bot_runtime.plugin_matrix.pip_extra_installed_for_plugin",
        lambda name: name == "duel",
    )
    assert should_load_bundled_plugin("duel", load_bundled_extra="auto") is False
    assert should_load_bundled_plugin("draw", load_bundled_extra="auto") is True


def test_protocol_extension_status_not_installed():
    from pallas.core.platform.bot_runtime.plugin_matrix import protocol_extension_status

    row = protocol_extension_status()
    assert row["package"] == "pallas-plugin-protocol"
    assert row["install_cli"] == "uv run pallas ext install pallas-plugin-protocol"
    assert row["activation_policy"] == "full-restart"


def test_is_core_and_extra_helpers():
    assert is_core_plugin("repeater")
    assert is_core_plugin("pb_stats")
    assert not is_core_plugin("duel")
    assert is_extra_plugin("draw")
    assert not is_extra_plugin("help")
    assert not is_extra_plugin("community_stats")


def test_installed_extra_plugin_modules_maa_role_split(monkeypatch):
    monkeypatch.setattr(
        "pallas.core.platform.bot_runtime.plugin_matrix.pip_module_installed",
        lambda mod: mod in {"pallas_plugin_maa", "pallas_plugin_maa_hub"},
    )
    hub_mods = installed_extra_plugin_modules(hub=True)
    worker_mods = installed_extra_plugin_modules(hub=False)
    assert "pallas_plugin_maa_hub" in hub_mods
    assert "pallas_plugin_maa" not in hub_mods
    assert "pallas_plugin_maa" in worker_mods
    assert "pallas_plugin_maa_hub" not in worker_mods


def test_resolve_hub_bundled_module_paths_skips_missing_extra(monkeypatch):
    monkeypatch.setattr(
        "pallas.core.platform.bot_runtime.plugin_matrix.should_load_bundled_plugin",
        lambda name, load_bundled_extra=None: True,
    )
    monkeypatch.setattr(
        "pallas.core.platform.bot_runtime.plugin_matrix.importlib.util.find_spec",
        lambda mod: object() if mod != "packages.relogin_bot" else None,
    )

    mods = resolve_hub_bundled_module_paths()

    assert "packages.pb_webui" in mods
    assert "packages.relogin_bot" not in mods


def test_community_stats_canonical_alias():
    from pallas.core.platform.bot_runtime.plugin_package_aliases import canonical_plugin_package

    assert canonical_plugin_package("community_stats") == "pb_stats"
    assert canonical_plugin_package("ollama") == "llm_chat"
    assert canonical_plugin_package("pallas_plugin_llm_chat") == "llm_chat"
    assert canonical_plugin_package("pallas_plugin_draw") == "draw"
    assert is_core_plugin("community_stats")
    assert is_core_plugin("ollama")

    expected_pip_aliases = {
        "pallas_plugin_protocol": "pb_protocol",
        "pallas_plugin_relogin_bot": "relogin_bot",
        "pallas_plugin_relogin_forward": "relogin_forward",
        "pallas_plugin_duel": "duel",
        "pallas_plugin_who_is_spy": "who_is_spy",
        "pallas_plugin_dream": "dream",
        "pallas_plugin_maa": "maa",
        "pallas_plugin_maa_hub": "maa_hub",
        "pallas_plugin_draw": "draw",
        "pallas_plugin_sing": "sing",
        "pallas_plugin_chat": "chat",
        "pallas_plugin_bot_status": "bot_status",
    }
    all_modules = {mod for modules in EXTRA_PACKAGE_MODULES.values() for mod in modules}
    for mod, canonical in expected_pip_aliases.items():
        assert mod in all_modules
        assert canonical_plugin_package(mod) == canonical


def test_official_extension_description_prefers_readme_summary():
    assert official_extension_description("pallas-plugin-draw") == "按文字描述生图，或带参考图改图。"
    assert official_extension_description("pallas-plugin-protocol") == "管理 NapCat 和 SnowLuma 协议端实例与连接配置。"


def test_official_extension_description_falls_back_for_multi_plugin_package():
    assert official_extension_description("pallas-plugin-ai-media") == "唱歌（sing）与 酒后聊天（chat）。"


def test_official_extension_display_name_uses_chinese_titles():
    assert official_extension_display_name("pallas-plugin-maa") == "MAA 远控"
    assert official_extension_display_name("pallas-plugin-ai-media") == "唱歌 / 酒后聊天"
    assert official_extension_display_name("pallas-plugin-unknown") == "unknown"


def test_official_extension_visuals_use_official_repo_assets() -> None:
    visuals = official_extension_visuals("pallas-plugin-draw")
    assert visuals["avatar"] is None
    assert visuals["icon"] == visuals["cover"]
    assert (
        visuals["cover"]
        == "https://raw.githubusercontent.com/TogetsuDo/pallas-plugin-draw/main/assets/brand-avatar.png"
    )
