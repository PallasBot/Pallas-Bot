from packages.help import __plugin_meta__


def test_help_metadata_uses_sdk_declarations():
    perms = __plugin_meta__.extra.get("command_permissions") or []
    limits = __plugin_meta__.extra.get("command_limits") or []
    storage = __plugin_meta__.extra.get("plugin_storage") or []
    assert len(perms) == 5
    assert limits[0]["id"] == "help.help"
    assert __plugin_meta__.extra.get("reload_policy") == "metadata"
    assert {row["key"] for row in storage} == {"hidden_plugins", "global_disabled_plugins"}


def test_help_renderer_is_a_webui_select_field():
    from packages.help.config import Config
    from pallas.console.webui.field_meta import field_meta_for_model_field
    from pallas.console.webui.plugin_api import plugin_field_env_key

    field = Config.model_fields["renderer"]
    row = field_meta_for_model_field(
        key="renderer",
        field=field,
        env_key=plugin_field_env_key("help", "renderer"),
        cur="pillow",
        default_value="pillow",
    )

    assert row["kind"] == "enum"
    assert row["choices"] == ["pillow", "html"]
    assert row["env_key"] == "PALLAS_HELP_RENDERER"
