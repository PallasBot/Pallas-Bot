import pytest

from src.console.webui.extension_install import (
    ExtensionInstallError,
    official_extension_packages,
    resolve_official_extension_package,
)
from src.console.webui.plugin_registry import build_official_extension_rows


def test_official_extension_packages_covers_matrix_repos():
    from src.platform.bot_runtime.plugin_matrix import OFFICIAL_EXTENSION_REPOS

    assert official_extension_packages() == frozenset(OFFICIAL_EXTENSION_REPOS.keys())


def test_resolve_rejects_unknown_package():
    with pytest.raises(ExtensionInstallError):
        resolve_official_extension_package("pallas-plugin-not-real")


def test_build_official_extension_rows_webui_install_flag():
    rows = build_official_extension_rows()
    duel = next(r for r in rows if r["package"] == "pallas-plugin-duel")
    assert isinstance(duel["webui_install"], bool)
    assert isinstance(duel["pip_installed"], bool)
    assert isinstance(duel["can_install"], bool)
    assert isinstance(duel["can_uninstall"], bool)
    assert duel["webui_install"] is True
