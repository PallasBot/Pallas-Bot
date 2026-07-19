from __future__ import annotations

from pathlib import Path  # noqa: TC003

from pallas.core.platform.bot_runtime.pyproject_plugins import (
    extra_plugin_dirs_for_role,
    parse_nonebot_plugin_config,
)


def test_parse_nonebot_plugin_config_new_format(tmp_path: Path):
    toml = tmp_path / "pyproject.toml"
    toml.write_text(
        """
[tool.nonebot]
plugin_dirs = ["packages", "extra_plugins"]

[tool.nonebot.plugins]
"@local" = []
nonebot-plugin-apscheduler = ["nonebot_plugin_apscheduler"]
my-pack = ["my_pack_plugin"]
""",
        encoding="utf-8",
    )
    modules, dirs = parse_nonebot_plugin_config(toml)
    assert "nonebot_plugin_apscheduler" in modules
    assert "my_pack_plugin" in modules
    assert dirs == ["packages", "extra_plugins"]


def test_parse_nonebot_plugin_config_legacy_list(tmp_path: Path):
    toml = tmp_path / "pyproject.toml"
    toml.write_text(
        """
[tool.nonebot]
plugins = ["legacy_plugin"]
plugin_dirs = []
""",
        encoding="utf-8",
    )
    modules, dirs = parse_nonebot_plugin_config(toml)
    assert modules == ["legacy_plugin"]
    assert dirs == []


def test_extra_plugin_dirs_skips_default():
    assert extra_plugin_dirs_for_role(["packages", "./extra"]) == ["./extra"]
