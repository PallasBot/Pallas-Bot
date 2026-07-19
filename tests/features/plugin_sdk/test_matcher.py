from pallas.core.commands.matcher import _plugin_tag_from_command_id


def test_plugin_tag_from_command_id():
    assert _plugin_tag_from_command_id("pb_core.status") == "pb_core"
    assert _plugin_tag_from_command_id("praise_me.praise") == "praise_me"
    assert _plugin_tag_from_command_id("") == "plugin"
