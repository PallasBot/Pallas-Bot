from __future__ import annotations

from typing import TYPE_CHECKING

from tools.check_plugin_identity_imports import find_forbidden_plugin_imports

if TYPE_CHECKING:
    from pathlib import Path


def test_find_forbidden_plugin_imports_flags_legacy_extra_plugin_paths(tmp_path: Path) -> None:
    path = tmp_path / "demo.py"
    path.write_text("from packages.bot_status import __plugin_meta__\n", encoding="utf-8")

    hits = find_forbidden_plugin_imports([path])

    assert hits == [(path, 1, "packages.bot_status")]


def test_find_forbidden_plugin_imports_flags_direct_pip_plugin_modules(tmp_path: Path) -> None:
    path = tmp_path / "demo.py"
    path.write_text("import pallas_plugin_relogin_bot.service\n", encoding="utf-8")

    hits = find_forbidden_plugin_imports([path])

    assert hits == [(path, 1, "pallas_plugin_relogin_bot")]


def test_find_forbidden_plugin_imports_ignores_safe_files(tmp_path: Path) -> None:
    path = tmp_path / "demo.py"
    path.write_text("from packages.help import __plugin_meta__\n", encoding="utf-8")

    assert find_forbidden_plugin_imports([path]) == []
